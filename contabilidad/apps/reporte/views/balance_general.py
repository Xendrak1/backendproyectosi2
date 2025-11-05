# apps/reporte/views/balance_general.py
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Q, DecimalField
from django.db.models.functions import Coalesce
from ...gestion_cuenta.models import ClaseCuenta, Cuenta
from ...gestion_asiento.models import Movimiento
from datetime import date, datetime, timedelta 
from ..services.pdf import render_to_pdf, build_pdf_response
from decimal import Decimal

class BalanceGeneralViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    pagination_class = None  # desactiva paginación

    def _get_empresa(self, request):
        """Función helper para obtener la empresa de forma segura."""
        if hasattr(request, 'empresa_id') and request.empresa_id:
             return request.empresa_id
        
        # Fallback por si el middleware usa 'request.auth.get'
        if hasattr(request, 'auth') and request.auth:
             empresa = request.auth.get('empresa')
             if empresa:
                 return empresa.id
        
        # Fallback final para el usuario logueado
        if hasattr(request, 'user') and hasattr(request.user, 'user_empresa'):
            return request.user.user_empresa.empresa_id
            
        return None

    def _get_saldos_agregados(self, empresa_id, fecha_inicio, fecha_fin):
        """
        OPTIMIZACIÓN: Esta es la clave.
        Hace UNA sola consulta a la BBDD para obtener todos los saldos de TODAS
        las cuentas (Balance y Resultado) en los rangos de fecha necesarios.
        """
        
        # Saldos ACUMULADOS para Balance (Clases 1, 2, 3)
        saldos_balance = Movimiento.objects.filter(
            asiento_contable__empresa_id=empresa_id,
            asiento_contable__fecha__lte=fecha_fin, # <= Fecha Fin (Acumulado)
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
        
        # Saldos DEL PERIODO para Resultado (Clases 4, 5)
        saldos_resultado = Movimiento.objects.filter(
            asiento_contable__empresa_id=empresa_id,
            asiento_contable__fecha__range=[fecha_inicio, fecha_fin], # RANGO (del periodo)
            estado=True
        ).filter(
            Q(cuenta__clase_cuenta__codigo__startswith='4') |
            Q(cuenta__clase_cuenta__codigo__startswith='5')
        ).values(
            'cuenta__clase_cuenta__codigo' # Agrupamos solo por clase (4 o 5)
        ).annotate(
            total_debe=Coalesce(Sum('debe'), Decimal(0), output_field=DecimalField()),
            total_haber=Coalesce(Sum('haber'), Decimal(0), output_field=DecimalField())
        )

        # Convertir saldos de balance a un dict para búsqueda rápida
        saldos_balance_dict = {}
        for s in saldos_balance:
            saldo = s['total_debe'] - s['total_haber']
            # Solo agregar si tiene saldo
            if saldo != 0 or s['total_debe'] != 0 or s['total_haber'] != 0:
                saldos_balance_dict[s['cuenta_id']] = {
                    "codigo": s['cuenta__codigo'],
                    "nombre": s['cuenta__nombre'],
                    "total_debe": s['total_debe'],
                    "total_haber": s['total_haber'],
                    "saldo": saldo,
                    "clase_id": s['cuenta__clase_cuenta_id']
                }
        
        # Calcular resultado del ejercicio
        total_ingresos = Decimal(0)
        total_egresos = Decimal(0)
        for s in saldos_resultado:
            if str(s['cuenta__clase_cuenta__codigo']).startswith('4'):
                total_ingresos = s['total_haber'] - s['total_debe'] # Acreedor
            elif str(s['cuenta__clase_cuenta__codigo']).startswith('5'):
                total_egresos = s['total_debe'] - s['total_haber'] # Deudor
        
        resultado_ejercicio = total_ingresos - total_egresos

        return saldos_balance_dict, resultado_ejercicio

    def _calcular_saldo_recursivo(self, clase, saldos_dict):
        """
        Función recursiva MEJORADA.
        Ya no hace consultas a la BBDD, solo lee del 'saldos_dict'.
        """
        
        # 1. Procesar cuentas (hojas) de esta clase
        cuentas_data = []
        
        # Buscamos en el dict las cuentas que pertenecen a esta clase
        for cuenta_id, saldo_info in saldos_dict.items():
            if saldo_info['clase_id'] == clase.id:
                cuentas_data.append({
                    "codigo": saldo_info['codigo'],
                    "nombre": saldo_info['nombre'],
                    "total_debe": saldo_info['total_debe'],
                    "total_haber": saldo_info['total_haber'],
                    "saldo": saldo_info['saldo'],
                    "hijos": [], # Las cuentas son hojas
                })

        # 2. Procesar subclases (hijos)
        hijos_data = []
        total_debe_hijos = Decimal(0)
        total_haber_hijos = Decimal(0)
        
        for hijo in clase.hijos.all(): # .all() es rápido por el prefetch_related
            hijo_data = self._calcular_saldo_recursivo(hijo, saldos_dict)
            if hijo_data: # Solo añadir si el hijo tiene saldo
                hijos_data.append(hijo_data)
                total_debe_hijos += hijo_data['total_debe']
                total_haber_hijos += hijo_data['total_haber']

        # 3. Calcular totales para ESTA clase
        total_debe_propias = sum(c['total_debe'] for c in cuentas_data)
        total_haber_propias = sum(c['total_haber'] for c in cuentas_data)
        
        total_debe = total_debe_propias + total_debe_hijos
        total_haber = total_haber_propias + total_haber_hijos
        saldo = total_debe - total_haber
        
        # Combinar: primero mostrar cuentas directas, luego las subclases
        hijos_completos = cuentas_data + hijos_data

        # Optimización: Si no hay saldo ni hijos, no mostrar esta clase
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

        # 1. Obtener todos los saldos (Balance y Resultado) en una sola pasada
        saldos_dict, resultado_ejercicio = self._get_saldos_agregados(empresa_id, fecha_inicio_dt, fecha_fin_dt)

        # 2. Traer la estructura de Clases (solo 1, 2, 3)
        clases_raiz = (
            ClaseCuenta.objects.filter(empresa_id=empresa_id, padre=None, codigo__in=[1, 2, 3])
            .prefetch_related("hijos__hijos__cuentas", "hijos__cuentas", "cuentas") # Prefetch profundo
        ).order_by('codigo')

        # 3. Construir el reporte recursivamente (ahora es rápido)
        resultado = []
        patrimonio_node = None
        for clase in clases_raiz:
            clase_data = self._calcular_saldo_recursivo(clase, saldos_dict)
            if clase_data:
                resultado.append(clase_data)
                if clase_data['codigo'] == 3: # Guardar referencia al nodo Patrimonio
                    patrimonio_node = clase_data

        # 4. CÁLCULO CONTABLE CORRECTO: Inyectar Resultado del Ejercicio
        if patrimonio_node and resultado_ejercicio != 0:
            # Si es Utilidad (positivo), es un Haber (disminuye 'saldo' Deudor-Acreedor)
            # Si es Pérdida (negativo), es un Debe (aumenta 'saldo' Deudor-Acreedor)
            saldo_resultado = resultado_ejercicio * -1 

            resultado_node = {
                "codigo": "3.R", # Código inventado
                "nombre": "Resultado del Ejercicio (Utilidad/Pérdida)",
                "total_debe": abs(resultado_ejercicio) if resultado_ejercicio < 0 else Decimal(0), # Pérdida es Debe
                "total_haber": resultado_ejercicio if resultado_ejercicio > 0 else Decimal(0), # Utilidad es Haber
                "saldo": saldo_resultado,
                "hijos": [],
            }
            
            # Añadir al patrimonio
            patrimonio_node['hijos'].append(resultado_node)
            patrimonio_node['total_debe'] += resultado_node['total_debe']
            patrimonio_node['total_haber'] += resultado_node['total_haber']
            patrimonio_node['saldo'] += resultado_node['saldo']

        return Response(resultado)

    @action(detail=False, methods=["get"], url_path="export/pdf")
    def export_pdf(self, request):
        # --- 1. Reutilizar la lógica de 'list' para obtener los datos ---
        # (Se duplica la lógica aquí porque 'list' devuelve un Response)
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

        saldos_dict, resultado_ejercicio = self._get_saldos_agregados(empresa_id, fecha_inicio_dt, fecha_fin_dt)

        clases_raiz = (
            ClaseCuenta.objects.filter(empresa_id=empresa_id, padre=None, codigo__in=[1, 2, 3])
            .prefetch_related("hijos__hijos__cuentas", "hijos__cuentas", "cuentas")
        ).order_by('codigo')

        data = []
        patrimonio_node = None
        for clase in clases_raiz:
            clase_data = self._calcular_saldo_recursivo(clase, saldos_dict)
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
        
        # --- 2. Lógica de PDF (Tu código original) ---
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
            # Añadir empresa_nombre al contexto si tu plantilla lo usa
            "empresa_nombre": Empresa.objects.get(id=empresa_id).nombre if empresa_id else "Mi Empresa"
        }

        pdf = render_to_pdf("reporte/pdf/balance_general.html", context)
        filename = f"balance_general_{fecha_fin_str}.pdf"
        return build_pdf_response(pdf, filename)