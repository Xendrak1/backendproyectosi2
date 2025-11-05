from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets # ⬅️ ¡IMPORTACIÓN CLAVE!
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q, DecimalField
from django.db.models.functions import Coalesce
from datetime import date, datetime, timedelta
from decimal import Decimal

from ...gestion_cuenta.models import ClaseCuenta, Cuenta
from ...gestion_asiento.models import Movimiento
from ...empresa.models.empresa import Empresa
from ..services.pdf import render_to_pdf, build_pdf_response # ⬅️ Usamos tu importación

# ⬇️ ¡NOMBRE CORREGIDO! Usa 'ViewSet' como espera tu __init__.py
class EstadoResultadosViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    pagination_class = None

    # --- Funciones auxiliares (helper methods) ---
    
    def _get_empresa(self, request):
        """Función helper para obtener la empresa de forma segura."""
        if hasattr(request, 'empresa_id') and request.empresa_id:
             return request.empresa_id
        if hasattr(request, 'auth') and request.auth:
             empresa = request.auth.get('empresa')
             if empresa:
                 return empresa.id # ⬅️ ¡CORREGIDO!
        if hasattr(request, 'user') and hasattr(request.user, 'user_empresa'):
            return request.user.user_empresa.empresa_id
        return None

    def get_clases_raiz(self, empresa_id):
        # Solo obtenemos las raíces de Ingresos (4) y Egresos (5)
        return ClaseCuenta.objects.filter(
            empresa_id=empresa_id, 
            padre__isnull=True,
            codigo__in=[4, 5] # Solo clases 4 y 5
        ).order_by('codigo')

    def get_saldos_cuentas_resultado(self, empresa_id, fecha_inicio, fecha_fin):
        """
        Obtiene los saldos de todas las cuentas de Ingreso y Egreso
        (Clases 4, 5) para el RANGO de fechas.
        """
        saldos_qs = Movimiento.objects.filter(
            asiento_contable__empresa_id=empresa_id,
            asiento_contable__fecha__range=[fecha_inicio, fecha_fin], # RANGO de fechas
            estado=True
        ).filter(
            Q(cuenta__clase_cuenta__codigo__startswith='4') |
            Q(cuenta__clase_cuenta__codigo__startswith='5')
        ).values(
            'cuenta_id', 'cuenta__codigo', 'cuenta__nombre', 'cuenta__clase_cuenta_id',
            'cuenta__clase_cuenta__codigo' # Necesitamos el código de la clase
        ).annotate(
            total_debe=Coalesce(Sum('debe'), Decimal(0), output_field=DecimalField()),
            total_haber=Coalesce(Sum('haber'), Decimal(0), output_field=DecimalField())
        )
        
        # Convertir a un dict para búsqueda rápida
        saldos_dict = {}
        for s in saldos_qs:
            total_debe = s['total_debe']
            total_haber = s['total_haber']
            
            # Calcular 'net' (saldo según naturaleza)
            if str(s['cuenta__clase_cuenta__codigo']).startswith("4"):
                net = total_haber - total_debe # Ingreso (Acreedor)
            else:
                net = total_debe - total_haber # Egreso (Deudor)

            if net != 0:
                saldos_dict[s['cuenta_id']] = {
                    "codigo": s['cuenta__codigo'],
                    "nombre": s['cuenta__nombre'],
                    "total_debe": total_debe,
                    "total_haber": total_haber,
                    "net": net,
                    "clase_id": s['cuenta__clase_cuenta_id']
                }
        return saldos_dict

    def procesar_cuentas_recursivo(self, clase_actual, saldos_dict):
        """
        Función recursiva optimizada.
        """
        data = {
            "codigo": clase_actual.codigo,
            "nombre": clase_actual.nombre,
            "total_debe": Decimal(0),
            "total_haber": Decimal(0),
            "net": Decimal(0), # (Saldo según naturaleza)
            "hijos": []
        }

        hijos = clase_actual.hijos.filter(empresa_id=clase_actual.empresa_id)

        if hijos.exists():
            for hijo in hijos:
                hijo_data = self.procesar_cuentas_recursivo(hijo, saldos_dict)
                if hijo_data: 
                    data['hijos'].append(hijo_data)
                    data['net'] += hijo_data['net']
        else:
            cuentas = Cuenta.objects.filter(clase_cuenta=clase_actual, estado=True)
            for cuenta in cuentas:
                saldo_cuenta = saldos_dict.get(cuenta.id)
                
                if saldo_cuenta:
                    cuenta_neto = saldo_cuenta['net']
                    
                    if cuenta_neto != 0:
                        data['hijos'].append({
                            "codigo": saldo_cuenta['codigo'],
                            "nombre": saldo_cuenta['nombre'],
                            "total_debe": saldo_cuenta['total_debe'],
                            "total_haber": saldo_cuenta['total_haber'],
                            "net": cuenta_neto,
                            "hijos": [],
                        })
                        data['net'] += cuenta_neto

        # Optimización: Si no tiene saldo neto, no lo retornes
        if data['net'] == 0:
             return None

        return data

    # ⬇️ ¡RENOMBRADO A 'list'!
    def list(self, request):
        fecha_inicio_str = request.query_params.get("fecha_inicio", "2010-01-01")
        fecha_fin_str = request.query_params.get("fecha_fin", datetime.now().strftime("%Y-%m-%d"))

        try:
            fecha_inicio_dt = date.fromisoformat(fecha_inicio_str)
            fecha_fin_dt = date.fromisoformat(fecha_fin_str)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=400)

        empresa_id = self._get_empresa(request)
        if not empresa_id:
            return Response({"error": "Usuario sin empresa asignada"}, status=400)

        # 1. Obtener todos los saldos (Clases 4 y 5) en una sola pasada
        saldos_dict = self.get_saldos_cuentas_resultado(empresa_id, fecha_inicio_dt, fecha_fin_dt)

        # 2. Traer la estructura de Clases (solo 4, 5)
        clases_raiz = (
            ClaseCuenta.objects.filter(empresa_id=empresa_id, padre=None, codigo__in=[4, 5])
            .prefetch_related("hijos__hijos__cuentas", "hijos__cuentas", "cuentas")
        ).order_by('codigo')

        # 3. Construir el reporte recursivamente (ahora es rápido)
        resultado = []
        total_ingresos = Decimal(0)
        total_costos = Decimal(0)
        
        for clase in clases_raiz:
            clase_data = self.procesar_cuentas_recursivo(clase, saldos_dict)
            if clase_data:
                resultado.append(clase_data)
                if str(clase_data['codigo']).startswith("4"):
                    total_ingresos += clase_data['net']
                elif str(clase_data['codigo']).startswith("5"):
                    total_costos += clase_data['net']

        utilidad = total_ingresos - total_costos

        return Response({
            "data": resultado,
            "total_ingresos": total_ingresos,
            "total_costos": total_costos,
            "utilidad": utilidad,
        })

    @action(detail=False, methods=["get"], url_path="export/pdf")
    def export_pdf(self, request):
        # --- 1. Reutilizar la lógica de 'list' para obtener los datos ---
        fecha_inicio_str = request.query_params.get("fecha_inicio", "2010-01-01")
        fecha_fin_str = request.query_params.get("fecha_fin", datetime.now().strftime("%Y-%m-%d"))

        try:
            fecha_inicio_dt = date.fromisoformat(fecha_inicio_str)
            fecha_fin_dt = date.fromisoformat(fecha_fin_str)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=400)

        empresa_id = self._get_empresa(request)
        if not empresa_id:
            return Response({"error": "Usuario sin empresa asignada"}, status=400)

        saldos_dict = self.get_saldos_cuentas_resultado(empresa_id, fecha_inicio_dt, fecha_fin_dt)

        clases_raiz = (
            ClaseCuenta.objects.filter(empresa_id=empresa_id, padre=None, codigo__in=[4, 5])
            .prefetch_related("hijos__hijos__cuentas", "hijos__cuentas", "cuentas")
        ).order_by('codigo')

        data = []
        total_ingresos = Decimal(0)
        total_costos = Decimal(0)

        for clase in clases_raiz:
            clase_data = self.procesar_cuentas_recursivo(clase, saldos_dict)
            if clase_data:
                data.append(clase_data)
                if str(clase_data['codigo']).startswith("4"):
                    total_ingresos += clase_data['net']
                elif str(clase_data['codigo']).startswith("5"):
                    total_costos += clase_data['net']

        utilidad = total_ingresos - total_costos

        # --- 2. Lógica de PDF (Tu código original) ---
        context = {
            "fecha_inicio": fecha_inicio_str,
            "fecha_fin": fecha_fin_str,
            "data": data,
            "total_ingresos": total_ingresos,
            "total_costos": total_costos,
            "utilidad": utilidad,
            "empresa_nombre": Empresa.objects.get(id=empresa_id).nombre if empresa_id else "Mi Empresa"
        }

        # ⬇️ --- ¡USANDO TUS FUNCIONES CORRECTAS! --- ⬇️
        # (Tu archivo pdf.py tiene 'render_to_pdf_estado_resultado', pero no 'render_to_pdf' genérico)
        # Vamos a asumir que quieres usar la genérica que sí importaste.
        try:
            # Intenta usar la específica si existe (basado en tu otro archivo)
            from ..services.pdf import render_to_pdf_estado_resultado
            pdf = render_to_pdf_estado_resultado("reporte/pdf/estado_resultados.html", context)
        except ImportError:
            # Si no existe, usa la genérica
            pdf = render_to_pdf("reporte/pdf/estado_resultados.html", context)

        filename = f"estado_resultados_{fecha_fin_str}.pdf"
        return build_pdf_response(pdf, filename)