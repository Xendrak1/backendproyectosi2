from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets
from rest_framework.decorators import action # ⬅️ ¡AÑADIDO! Esta es la corrección
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from datetime import date, datetime, timedelta # ⬅️ 'date' y 'datetime' añadidos

# Importaciones de modelos
from ...gestion_cuenta.models.clase_cuenta import ClaseCuenta
from ...gestion_cuenta.models.cuenta import Cuenta
from ...gestion_asiento.models.movimiento import Movimiento
from ...empresa.models.empresa import Empresa

# Tus funciones PDF correctas
from ..services.pdf import render_to_pdf, build_pdf_response

# ⬇️ ¡HEREDA DE viewsets.ViewSet!
class BalanceGeneralViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    """
    Vista optimizada para el Balance General.
    """

    # --- Funciones auxiliares (helper methods) ---

    def _get_empresa(self, request):
        """Función helper para obtener la empresa de forma segura."""
        # ⬇️ ¡CORREGIDO! Tu lógica de 'request.auth.get' devuelve un objeto Empresa, no solo el ID.
        if hasattr(request, 'auth') and request.auth:
             empresa = request.auth.get('empresa')
             if empresa:
                 return empresa # Devolvemos el objeto Empresa completo
        
        # Fallback por si el middleware usa 'request.empresa_id' (como en mis versiones anteriores)
        if hasattr(request, 'empresa_id') and request.empresa_id:
             try:
                 return Empresa.objects.get(id=request.empresa_id)
             except Empresa.DoesNotExist:
                 pass
        
        # Fallback final para el usuario logueado
        if hasattr(request, 'user') and hasattr(request.user, 'user_empresa'):
            return request.user.user_empresa.empresa
            
        return None

    def get_clases_raiz(self, empresa_id):
        # Solo obtenemos las raíces del Balance: Activo, Pasivo, Patrimonio
        return ClaseCuenta.objects.filter(
            empresa_id=empresa_id, 
            padre__isnull=True,
            codigo__in=[1, 2, 3] # Solo clases 1, 2, 3
        ).order_by('codigo')

    def get_saldos_cuentas_balance(self, empresa_id, fecha_fin):
        """
        Obtiene los saldos de todas las cuentas de Activo, Pasivo y Patrimonio
        (Clases 1, 2, 3) hasta la fecha de corte.
        Retorna un diccionario para búsqueda rápida.
        """
        saldos_qs = Movimiento.objects.filter(
            asiento_contable__empresa_id=empresa_id,
            asiento_contable__fecha__lte=fecha_fin, # Saldo ACUMULADO
            estado=True
        ).filter(
            Q(cuenta__clase_cuenta__codigo__startswith='1') |
            Q(cuenta__clase_cuenta__codigo__startswith='2') |
            Q(cuenta__clase_cuenta__codigo__startswith='3')
        ).values(
            'cuenta_id', 'cuenta__codigo', 'cuenta__nombre', 'cuenta__clase_cuenta_id'
        ).annotate(
            total_debe=Coalesce(Sum('debe'), Decimal(0), output_field=DecimalField()),
            total_haber=Coalesce(Sum('haber'), Decimal(0), output_field=DecimalField())
        )

        saldos_dict = {}
        for s in saldos_qs:
            saldo = s['total_debe'] - s['total_haber']
            if saldo != 0 or s['total_debe'] != 0 or s['total_haber'] != 0:
                saldos_dict[s['cuenta_id']] = {
                    "codigo": s['cuenta__codigo'],
                    "nombre": s['cuenta__nombre'],
                    "total_debe": s['total_debe'],
                    "total_haber": s['total_haber'],
                    "saldo": saldo,
                    "clase_id": s['cuenta__clase_cuenta_id']
                }
        return saldos_dict

    def get_resultado_del_ejercicio(self, empresa_id, fecha_inicio, fecha_fin):
        """
        Calcula la Utilidad o Pérdida del Ejercicio (Ingresos - Egresos)
        para el PERIODO especificado.
        """
        
        # 1. Total Ingresos (Clase 4)
        ingresos_agg = Movimiento.objects.filter(
            asiento_contable__empresa_id=empresa_id,
            asiento_contable__fecha__range=[fecha_inicio, fecha_fin], 
            estado=True,
            cuenta__clase_cuenta__codigo__startswith='4'
        ).aggregate(
            total_debe=Coalesce(Sum('debe'), Decimal(0)),
            total_haber=Coalesce(Sum('haber'), Decimal(0))
        )
        total_ingresos = ingresos_agg['total_haber'] - ingresos_agg['total_debe']

        # 2. Total Egresos (Clase 5)
        egresos_agg = Movimiento.objects.filter(
            asiento_contable__empresa_id=empresa_id,
            asiento_contable__fecha__range=[fecha_inicio, fecha_fin],
            estado=True,
            cuenta__clase_cuenta__codigo__startswith='5'
        ).aggregate(
            total_debe=Coalesce(Sum('debe'), Decimal(0)),
            total_haber=Coalesce(Sum('haber'), Decimal(0))
        )
        total_egresos = egresos_agg['total_debe'] - egresos_agg['total_haber']
        
        # 3. Resultado (Ingresos - Egresos)
        return total_ingresos - total_egresos

    def procesar_cuentas_recursivo(self, clase, saldos_dict):
        """
        Función recursiva MEJORADA.
        Ya no hace consultas a la BBDD, solo lee del 'saldos_dict'.
        """
        
        cuentas_data = []
        for cuenta_id, saldo_info in saldos_dict.items():
            if saldo_info['clase_id'] == clase.id:
                cuentas_data.append({
                    "codigo": saldo_info['codigo'],
                    "nombre": saldo_info['nombre'],
                    "total_debe": saldo_info['total_debe'],
                    "total_haber": saldo_info['total_haber'],
                    "saldo": saldo_info['saldo'],
                    "hijos": [],
                })

        hijos_data = []
        total_debe_hijos = Decimal(0)
        total_haber_hijos = Decimal(0)
        
        for hijo in clase.hijos.all(): # .all() es rápido por el prefetch_related
            hijo_data = self.procesar_cuentas_recursivo(hijo, saldos_dict)
            if hijo_data: 
                hijos_data.append(hijo_data)
                total_debe_hijos += hijo_data['total_debe']
                total_haber_hijos += hijo_data['total_haber']

        total_debe_propias = sum(c['total_debe'] for c in cuentas_data)
        total_haber_propias = sum(c['total_haber'] for c in cuentas_data)
        
        total_debe = total_debe_propias + total_debe_hijos
        total_haber = total_haber_propias + total_haber_hijos
        saldo = total_debe - total_haber
        
        hijos_completos = cuentas_data + hijos_data

        if not hijos_completos:
             return None

        return {
            "codigo": clase.codigo,
            "nombre": clase.nombre,
            "total_debe": total_debe,
            "total_haber": total_haber,
            "saldo": saldo,
            "hijos": hijos_completos,
        }

    # ⬇️ ¡RENOMBRADO A 'list'! Esta es la acción que el router buscará para GET /balance_general/
    def list(self, request, *args, **kwargs):
        fecha_inicio_str = request.query_params.get("fecha_inicio", "2010-01-01")
        fecha_fin_str = request.query_params.get("fecha_fin", datetime.now().strftime("%Y-%m-%d"))

        try:
            fecha_inicio_dt = date.fromisoformat(fecha_inicio_str)
            fecha_fin_dt = date.fromisoformat(fecha_fin_str)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=400)

        empresa = self._get_empresa(request) # ⬅️ Obtenemos el objeto Empresa
        if not empresa:
            return Response({"error": "Usuario sin empresa asignada"}, status=400)
        
        empresa_id = empresa.id # ⬅️ Obtenemos el ID

        saldos_dict, resultado_ejercicio = self._get_saldos_agregados(empresa_id, fecha_inicio_dt, fecha_fin_dt)

        clases_raiz = (
            ClaseCuenta.objects.filter(empresa_id=empresa_id, padre=None, codigo__in=[1, 2, 3])
            .prefetch_related("hijos__hijos__cuentas", "hijos__cuentas", "cuentas") # Prefetch profundo
        ).order_by('codigo')

        resultado = []
        patrimonio_node = None
        for clase in clases_raiz:
            clase_data = self.procesar_cuentas_recursivo(clase, saldos_dict)
            if clase_data:
                resultado.append(clase_data)
                if clase_data['codigo'] == 3: # Guardar referencia al nodo Patrimonio
                    patrimonio_node = clase_data

        if patrimonio_node and resultado_ejercicio != 0:
            saldo_resultado = resultado_ejercicio * -1 
            resultado_node = {
                "codigo": "3.R", 
                "nombre": "Resultado del Ejercicio (Utilidad/Pérdida)",
                "total_debe": abs(resultado_ejercicio) if resultado_ejercicio < 0 else Decimal(0), # Pérdida es Debe
                "total_haber": resultado_ejercicio if resultado_ejercicio > 0 else Decimal(0), # Utilidad es Haber
                "saldo": saldo_resultado,
                "hijos": [],
            }
            patrimonio_node['hijos'].append(resultado_node)
            patrimonio_node['total_debe'] += resultado_node['total_debe']
            patrimonio_node['total_haber'] += resultado_node['total_haber']
            patrimonio_node['saldo'] += saldo_resultado

        return Response(resultado)

    @action(detail=False, methods=["get"], url_path="export/pdf")
    def export_pdf(self, request):
        fecha_inicio_str = request.query_params.get("fecha_inicio", "2010-01-01")
        fecha_fin_str = request.query_params.get("fecha_fin", datetime.now().strftime("%Y-%m-%d"))

        try:
            fecha_inicio_dt = date.fromisoformat(fecha_inicio_str)
            fecha_fin_dt = date.fromisoformat(fecha_fin_str)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=400)

        empresa = self._get_empresa(request)
        if not empresa:
            return Response({"error": "Usuario sin empresa asignada"}, status=400)
        empresa_id = empresa.id
        
        saldos_dict, resultado_ejercicio = self._get_saldos_agregados(empresa_id, fecha_inicio_dt, fecha_fin_dt)

        clases_raiz = (
            ClaseCuenta.objects.filter(empresa_id=empresa_id, padre=None, codigo__in=[1, 2, 3])
            .prefetch_related("hijos__hijos__cuentas", "hijos__cuentas", "cuentas")
        ).order_by('codigo')

        data = []
        patrimonio_node = None
        for clase in clases_raiz:
            clase_data = self.procesar_cuentas_recursivo(clase, saldos_dict)
            if clase_data:
                data.append(clase_data)
                if clase_data['codigo'] == 3:
                    patrimonio_node = clase_data
        
        if patrimonio_node and resultado_ejercicio != 0:
            saldo_resultado = resultado_ejercicio * -1 
            resultado_node = {
                "codigo": "3.R",
                "nombre": "Resultado del Ejercicio (Utilidad/Pérdida)",
                "total_debe": abs(resultado_ejercicio) if resultado_ejercicio < 0 else Decimal(0),
                "total_haber": resultado_ejercicio if resultado_ejercicio > 0 else Decimal(0),
                "saldo": saldo_resultado,
                "hijos": [],
            }
            patrimonio_node['hijos'].append(resultado_node)
            patrimonio_node['total_debe'] += resultado_node['total_debe']
            patrimonio_node['total_haber'] += resultado_node['total_haber']
            patrimonio_node['saldo'] += resultado_node['saldo']
        
        total_debe = sum((n.get("total_debe") or 0) for n in data)
        total_haber = sum((n.get("total_haber") or 0) for n in data)
        totales = {
            "debe": total_debe,
            "haber": total_haber,
            "saldo": total_debe - total_haber,
        }

        context = {
            "fecha_inicio": fecha_inicio_str,
            "fecha_fin": fecha_fin_str,
            "data": data,
            "totales": totales,
            "empresa_nombre": empresa.nombre if empresa else "Mi Empresa"
        }

        pdf = render_to_pdf("reporte/pdf/balance_general.html", context)
        filename = f"balance_general_{fecha_fin_str}.pdf"
        return build_pdf_response(pdf, filename)