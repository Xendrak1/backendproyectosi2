from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated  # ⬅️ ¡CORRECCIÓN! Usamos el permiso estándar
from django.db.models import Sum, Q, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from datetime import date

# Importaciones de modelos
from ...gestion_cuenta.models.clase_cuenta import ClaseCuenta
from ...gestion_cuenta.models.cuenta import Cuenta
from ...gestion_asiento.models.movimiento import Movimiento
from ...empresa.models.empresa import Empresa

# Importaciones de PDF (ya las tenías)
from ..services.pdf import render_to_pdf_estado_resultado

# ⬇️ ¡CORRECCIÓN! Heredamos de APIView y usamos permission_classes
class EstadoResultadosView(APIView):
    permission_classes = [IsAuthenticated] # ⬅️ ¡CORRECCIÓN!

    """
    Vista optimizada para el Estado de Resultados.
    Utiliza agregaciones de base de datos para ser eficiente.
    """

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
        Retorna un diccionario para búsqueda rápida.
        """
        saldos_qs = Movimiento.objects.filter(
            asiento_contable__empresa_id=empresa_id,
            asiento_contable__fecha__range=[fecha_inicio, fecha_fin], # RANGO de fechas
            estado=True
        ).filter(
            # Filtramos solo por cuentas de resultado
            Q(cuenta__clase_cuenta__codigo__startswith='4') |
            Q(cuenta__clase_cuenta__codigo__startswith='5')
        ).values(
            'cuenta_id' # Agrupamos por cuenta
        ).annotate(
            total_debe=Coalesce(Sum('debe'), Decimal(0), output_field=DecimalField()),
            total_haber=Coalesce(Sum('haber'), Decimal(0), output_field=DecimalField())
        ).order_by('cuenta_id')

        # Convertir a un diccionario para acceso O(1)
        saldos_dict = {
            item['cuenta_id']: {
                'total_debe': item['total_debe'],
                'total_haber': item['total_haber'],
                # Saldo (Debe - Haber)
                'neto': item['total_debe'] - item['total_haber']
            } for item in saldos_qs
        }
        return saldos_dict

    def procesar_cuentas_recursivo(self, clase_actual, saldos_dict):
        """
        Función recursiva optimizada.
        Construye el árbol y calcula saldos basado en el diccionario pre-calculado.
        """
        data = {
            "codigo": clase_actual.codigo,
            "nombre": clase_actual.nombre,
            "total_debe": Decimal(0),
            "total_haber": Decimal(0),
            "neto": Decimal(0), # (Debe - Haber)
            "saldo": Decimal(0), # (Saldo según naturaleza)
            "hijos": []
        }

        # ⬇️ ¡OPTIMIZACIÓN! Usamos prefetch_related o select_related en la consulta principal si es necesario
        #    Pero para esta estructura, es mejor filtrar por la empresa
        hijos = clase_actual.hijos.filter(empresa_id=clase_actual.empresa_id)

        if hijos.exists():
            # Es una Clase Padre (Agregadora)
            for hijo in hijos:
                hijo_data = self.procesar_cuentas_recursivo(hijo, saldos_dict)
                if hijo_data: # Solo añadir si el hijo tiene datos
                    data['hijos'].append(hijo_data)
                    data['total_debe'] += hijo_data['total_debe']
                    data['total_haber'] += hijo_data['total_haber']
                    data['neto'] += hijo_data['neto']
        else:
            # Es una Clase Hoja (Contiene Cuentas)
            cuentas = Cuenta.objects.filter(clase_cuenta=clase_actual, estado=True)
            for cuenta in cuentas:
                saldo_cuenta = saldos_dict.get(cuenta.id)
                
                if saldo_cuenta:
                    cuenta_debe = saldo_cuenta['total_debe']
                    cuenta_haber = saldo_cuenta['total_haber']
                    cuenta_neto = saldo_cuenta['neto']
                    
                    if cuenta_debe != 0 or cuenta_haber != 0:
                        data['hijos'].append({
                            "codigo": cuenta.codigo,
                            "nombre": cuenta.nombre,
                            "total_debe": cuenta_debe,
                            "total_haber": cuenta_haber,
                            "neto": cuenta_neto,
                            "saldo": cuenta_neto * -1 if str(cuenta.codigo).startswith('4') else cuenta_neto
                        })
                        data['total_debe'] += cuenta_debe
                        data['total_haber'] += cuenta_haber
                        data['neto'] += cuenta_neto

        # Calcular el saldo total de esta clase según su naturaleza
        # Clase 4 (Ingresos) = Acreedor (Haber - Debe = Neto * -1)
        # Clase 5 (Egresos) = Deudor (Debe - Haber = Neto)
        if str(clase_actual.codigo).startswith('4'):
            data['saldo'] = data['neto'] * -1
        else:
            data['saldo'] = data['neto']

        # Optimización: Si no tiene saldo neto, no lo retornes
        if data['neto'] == 0:
             return None

        return data

    def get(self, request, *args, **kwargs):
        # ⬇️ ¡CORRECCIÓN! Obtenemos el ID de la empresa desde el middleware
        try:
            empresa_id = request.user.user_empresa.empresa_id
        except AttributeError:
            return Response({"error": "No se pudo determinar la empresa. ¿Middleware está activo?"}, status=401)
        
        # --- Obtener filtros de fecha ---
        fecha_inicio_str = request.query_params.get('fecha_inicio', date(date.today().year, 1, 1).strftime('%Y-%m-%d'))
        fecha_fin_str = request.query_params.get('fecha_fin', date.today().strftime('%Y-%m-%d'))

        try:
            fecha_inicio = date.fromisoformat(fecha_inicio_str)
            fecha_fin = date.fromisoformat(fecha_fin_str)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        # --- 1. Obtener saldos de cuentas (Clases 4, 5) ---
        saldos_dict = self.get_saldos_cuentas_resultado(empresa_id, fecha_inicio, fecha_fin)

        # --- 2. Construir el árbol de Resultados (Clases 4, 5) ---
        clases_raiz = self.get_clases_raiz(empresa_id)
        
        data_reporte = []
        total_ingresos = Decimal(0)
        total_costos = Decimal(0)
        
        for clase in clases_raiz:
            data_clase = self.procesar_cuentas_recursivo(clase, saldos_dict)
            if data_clase:
                data_reporte.append(data_clase)
                # Acumular totales
                if str(clase.codigo).startswith('4'):
                    total_ingresos += data_clase['saldo']
                elif str(clase.codigo).startswith('5'):
                    total_costos += data_clase['saldo']

        # --- 3. Calcular Utilidad/Pérdida ---
        utilidad = total_ingresos - total_costos

        # --- 4. Ensamblar respuesta final ---
        response_data = {
            "data": data_reporte,
            "total_ingresos": total_ingresos,
            "total_costos": total_costos,
            "utilidad": utilidad
        }
        
        return Response(response_data)


# Vista de PDF (Corregida)
class EstadoResultadosPDFView(EstadoResultadosView):
    # Hereda el permission_classes = [IsAuthenticated]
    
    def get(self, request, *args, **kwargs):
        
        # 1. Obtener los datos llamando al 'get' de la clase padre
        response_data = super().get(request, *args, **kwargs)
        
        if isinstance(response_data, Response):
             # Si el padre devolvió un error (ej. fecha inválida), lo retornamos
            if response_data.status_code != 200:
                return response_data
            data = response_data.data
        else:
            data = response_data
            
        # 2. Obtener fechas para el título del PDF
        fecha_inicio_str = request.query_params.get('fecha_inicio', date(date.today().year, 1, 1).strftime('%Y-%m-%d'))
        fecha_fin_str = request.query_params.get('fecha_fin', date.today().strftime('%Y-%m-%d'))

        # 3. Obtener nombre de la empresa
        empresa = None
        try:
            # ⬇️ ¡CORRECCIÓN! Usamos el ID de la empresa del request
            empresa_id = request.user.user_empresa.empresa_id
            empresa = Empresa.objects.get(id=empresa_id)
        except (AttributeError, Empresa.DoesNotExist):
            pass # Dejar empresa=None si no se encuentra
        
        # 4. Generar el PDF
        # El contexto debe coincidir con la plantilla HTML
        pdf_context = {
            'empresa_nombre': empresa.nombre if empresa else 'Mi Empresa',
            'fecha_inicio': fecha_inicio_str,
            'fecha_fin': fecha_fin_str,
            'data': data.get('data', []), # 'data' es la lista de clases
            'total_ingresos': data.get('total_ingresos', 0),
            'total_costos': data.get('total_costos', 0),
            'utilidad': data.get('utilidad', 0)
        }
        
        pdf = render_to_pdf_estado_resultado('reporte/pdf/estado_resultados.html', pdf_context)
        
        # 5. Devolver el PDF como respuesta
        return pdf
