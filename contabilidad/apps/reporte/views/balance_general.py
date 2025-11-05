from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Q, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from datetime import date, datetime, timedelta

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
            'cuenta_id' # Agrupamos por cuenta
        ).annotate(
            total_debe=Coalesce(Sum('debe'), Decimal(0), output_field=DecimalField()),
            total_haber=Coalesce(Sum('haber'), Decimal(0), output_field=DecimalField())
        ).order_by('cuenta_id')

        saldos_dict = {
            item['cuenta_id']: {
                'total_debe': item['total_debe'],
                'total_haber': item['total_haber'],
                'saldo': item['total_debe'] - item['total_haber']
            } for item in saldos_qs
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

    def procesar_cuentas_recursivo(self, clase_actual, saldos_dict):
        """
        Función recursiva optimizada.
        """
        data = {
            "codigo": clase_actual.codigo,
            "nombre": clase_actual.nombre,
            "total_debe": Decimal(0),
            "total_haber": Decimal(0),
            "saldo": Decimal(0),
            "hijos": []
        }

        hijos = clase_actual.hijos.filter(empresa_id=clase_actual.empresa_id)

        if hijos.exists():
            for hijo in hijos:
                hijo_data = self.procesar_cuentas_recursivo(hijo, saldos_dict)
                if hijo_data: 
                    data['hijos'].append(hijo_data)
                    data['total_debe'] += hijo_data['total_debe']
                    data['total_haber'] += hijo_data['total_haber']
        else:
            cuentas = Cuenta.objects.filter(clase_cuenta=clase_actual, estado=True)
            for cuenta in cuentas:
                saldo_cuenta = saldos_dict.get(cuenta.id)
                
                if saldo_cuenta:
                    cuenta_debe = saldo_cuenta['total_debe']
                    cuenta_haber = saldo_cuenta['total_haber']
                    cuenta_saldo = saldo_cuenta['saldo']
                    
                    if cuenta_debe != 0 or cuenta_haber != 0:
                        data['hijos'].append({
                            "codigo": cuenta.codigo,
                            "nombre": cuenta.nombre,
                            "total_debe": cuenta_debe,
                            "total_haber": cuenta_haber,
                            "saldo": cuenta_saldo
                        })
                        data['total_debe'] += cuenta_debe
                        data['total_haber'] += cuenta_haber

        data['saldo'] = data['total_debe'] - data['total_haber']
        
        if data['saldo'] == 0 and not data['hijos']:
             return None
        return data

    # ⬇️ ¡RENOMBRADO A 'list'! Esta es la acción que el router buscará para GET /balance_general/
    def list(self, request, *args, **kwargs):
        try:
            empresa_id = request.user.user_empresa.empresa_id
        except AttributeError:
            return Response({"error": "No se pudo determinar la empresa. ¿Middleware está activo?"}, status=401)
        
        fecha_inicio_str = request.query_params.get('fecha_inicio', date(date.today().year, 1, 1).strftime('%Y-%m-%d'))
        fecha_fin_str = request.query_params.get('fecha_fin', date.today().strftime('%Y-%m-%d'))

        try:
            fecha_inicio = date.fromisoformat(fecha_inicio_str)
            fecha_fin = date.fromisoformat(fecha_fin_str)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        saldos_dict = self.get_saldos_cuentas_balance(empresa_id, fecha_fin)
        resultado_ejercicio = self.get_resultado_del_ejercicio(empresa_id, fecha_inicio, fecha_fin)
        clases_raiz = self.get_clases_raiz(empresa_id)
        response_data = []
        patrimonio_index = -1
        
        for i, clase in enumerate(clases_raiz):
            data_clase = self.procesar_cuentas_recursivo(clase, saldos_dict)
            if data_clase:
                response_data.append(data_clase)
                if data_clase['codigo'] == 3:
                    patrimonio_index = len(response_data) - 1
            
        if patrimonio_index != -1 and resultado_ejercicio != 0:
            resultado_data = {
                "codigo": "3.R", 
                "nombre": "Resultado del Ejercicio (Utilidad/Pérdida)",
                "total_debe": Decimal(0) if resultado_ejercicio > 0 else abs(resultado_ejercicio), # Pérdida = Debe
                "total_haber": resultado_ejercicio if resultado_ejercicio > 0 else Decimal(0), # Utilidad = Haber
                "saldo": resultado_ejercicio * -1, 
                "hijos": []
            }
            response_data[patrimonio_index]['hijos'].append(resultado_data)
            response_data[patrimonio_index]['total_debe'] += resultado_data['total_debe']
            response_data[patrimonio_index]['total_haber'] += resultado_data['total_haber']
            response_data[patrimonio_index]['saldo'] += resultado_data['saldo']

        return Response(response_data)


# Vista de PDF (Esta SÍ es una APIView porque está en urlpatterns)
class BalanceGeneralPDFView(APIView):
    permission_classes = [IsAuthenticated]

    # Re-definimos la lógica aquí ya que no podemos heredar de un ViewSet
    # y de una APIView al mismo tiempo de forma limpia.
    # Es más seguro re-implementar el 'get' copiando la lógica de 'list'.

    def get(self, request, *args, **kwargs):
        
        # --- 1. Copiamos la lógica de 'list' de la ViewSet ---
        try:
            empresa_id = request.user.user_empresa.empresa_id
        except AttributeError:
            return Response({"error": "No se pudo determinar la empresa. ¿Middleware está activo?"}, status=401)
        
        fecha_inicio_str = request.query_params.get('fecha_inicio', date(date.today().year, 1, 1).strftime('%Y-%m-%d'))
        fecha_fin_str = request.query_params.get('fecha_fin', date.today().strftime('%Y-%m-%d'))

        try:
            fecha_inicio = date.fromisoformat(fecha_inicio_str)
            fecha_fin = date.fromisoformat(fecha_fin_str)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        # Usamos los mismos helpers (que ahora son métodos estáticos o de la instancia)
        # Para simplificar, los duplicamos como métodos de esta clase
        
        saldos_dict = BalanceGeneralViewSet().get_saldos_cuentas_balance(empresa_id, fecha_fin)
        resultado_ejercicio = BalanceGeneralViewSet().get_resultado_del_ejercicio(empresa_id, fecha_inicio, fecha_fin)
        clases_raiz = BalanceGeneralViewSet().get_clases_raiz(empresa_id)
        
        response_data = []
        patrimonio_index = -1
        
        for i, clase in enumerate(clases_raiz):
            # 
            data_clase = BalanceGeneralViewSet().procesar_cuentas_recursivo(clase, saldos_dict)
            if data_clase:
                response_data.append(data_clase)
                if data_clase['codigo'] == 3:
                    patrimonio_index = len(response_data) - 1
            
        if patrimonio_index != -1 and resultado_ejercicio != 0:
            resultado_data = {
                "codigo": "3.R", 
                "nombre": "Resultado del Ejercicio (Utilidad/Pérdida)",
                "total_debe": Decimal(0) if resultado_ejercicio > 0 else abs(resultado_ejercicio),
                "total_haber": resultado_ejercicio if resultado_ejercicio > 0 else Decimal(0),
                "saldo": resultado_ejercicio * -1, 
                "hijos": []
            }
            response_data[patrimonio_index]['hijos'].append(resultado_data)
            response_data[patrimonio_index]['total_debe'] += resultado_data['total_debe']
            response_data[patrimonio_index]['total_haber'] += resultado_data['total_haber']
            response_data[patrimonio_index]['saldo'] += resultado_data['saldo']

        # --- 2. Lógica del PDF (Usando tu lógica) ---
        empresa = None
        try:
            empresa = Empresa.objects.get(id=empresa_id)
        except Empresa.DoesNotExist:
            pass 
        
        pdf_context = {
            'empresa_nombre': empresa.nombre if empresa else 'Mi Empresa',
            'fecha_inicio': fecha_inicio_str,
            'fecha_fin': fecha_fin_str,
            'data': response_data 
        }
        
        pdf = render_to_pdf('reporte/pdf/balance_general.html', pdf_context)
        filename = f"balance_general_{fecha_fin_str}.pdf"
        
        return build_pdf_response(pdf, filename)