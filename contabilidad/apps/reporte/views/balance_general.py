from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum, Q, DecimalField
from django.db.models.functions import Coalesce
from decimal import Decimal
from datetime import date

# Importaciones de modelos
from ...gestion_cuenta.models.clase_cuenta import ClaseCuenta
from ...gestion_cuenta.models.cuenta import Cuenta
from ...gestion_asiento.models.movimiento import Movimiento
from ...empresa.models.empresa import Empresa #Importación para el PDF

# --- ESTA ES LA CORRECCIÓN ---
# Importar el Mixin desde su ubicación REAL en la app 'usuario'
from ...usuario.views.auth import EmpresaPermissionsMixin 

# Importaciones de PDF (ya las tenías)
from ..services.pdf import render_to_pdf_balance_general

class BalanceGeneralView(EmpresaPermissionsMixin, APIView):
    """
    Vista optimizada para el Balance General.
    
    Esta vista calcula los saldos de las cuentas de balance (1, 2, 3) y
    calcula el resultado del ejercicio (4, 5) para inyectarlo en el patrimonio,
    asegurando que el balance siempre cuadre.
    
    Utiliza agregaciones de base de datos para ser eficiente.
    """

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
            # Filtramos solo por cuentas de balance
            Q(cuenta__clase_cuenta__codigo__startswith='1') |
            Q(cuenta__clase_cuenta__codigo__startswith='2') |
            Q(cuenta__clase_cuenta__codigo__startswith='3')
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
                'saldo': item['total_debe'] - item['total_haber']
            } for item in saldos_qs
        }
        return saldos_dict

    def get_resultado_del_ejercicio(self, empresa_id, fecha_inicio, fecha_fin):
        """
        Calcula la Utilidad o Pérdida del Ejercicio (Ingresos - Egresos)
        para el PERIODO especificado.
        """
        
        # 1. Total Ingresos (Clase 4) - Naturaleza Acreedora (Haber - Debe)
        ingresos_agg = Movimiento.objects.filter(
            asiento_contable__empresa_id=empresa_id,
            asiento_contable__fecha__range=[fecha_inicio, fecha_fin], # Es un RANGO
            estado=True,
            cuenta__clase_cuenta__codigo__startswith='4'
        ).aggregate(
            total_debe=Coalesce(Sum('debe'), Decimal(0)),
            total_haber=Coalesce(Sum('haber'), Decimal(0))
        )
        total_ingresos = ingresos_agg['total_haber'] - ingresos_agg['total_debe']

        # 2. Total Egresos (Clase 5) - Naturaleza Deudora (Debe - Haber)
        egresos_agg = Movimiento.objects.filter(
            asiento_contable__empresa_id=empresa_id,
            asiento_contable__fecha__range=[fecha_inicio, fecha_fin], # Es un RANGO
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
        Ya no recibe la lista de movimientos, sino el diccionario de saldos pre-calculado.
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
            # Es una Clase Padre (Agregadora)
            for hijo in hijos:
                hijo_data = self.procesar_cuentas_recursivo(hijo, saldos_dict)
                if hijo_data: # Solo añadir si el hijo tiene datos o saldos
                    data['hijos'].append(hijo_data)
                    data['total_debe'] += hijo_data['total_debe']
                    data['total_haber'] += hijo_data['total_haber']
        else:
            # Es una Clase Hoja (Contiene Cuentas)
            cuentas = Cuenta.objects.filter(clase_cuenta=clase_actual, estado=True)
            for cuenta in cuentas:
                saldo_cuenta = saldos_dict.get(cuenta.id)
                
                if saldo_cuenta:
                    cuenta_debe = saldo_cuenta['total_debe']
                    cuenta_haber = saldo_cuenta['total_haber']
                    cuenta_saldo = saldo_cuenta['saldo']
                    
                    # Solo incluir cuentas con saldo
                    if cuenta_debe != 0 or cuenta_haber != 0:
                        # Añadir la cuenta individual como "hijo"
                        data['hijos'].append({
                            "codigo": cuenta.codigo,
                            "nombre": cuenta.nombre,
                            "total_debe": cuenta_debe,
                            "total_haber": cuenta_haber,
                            "saldo": cuenta_saldo
                        })
                        
                        # Sumar al total de la clase
                        data['total_debe'] += cuenta_debe
                        data['total_haber'] += cuenta_haber

        # Calcular el saldo total de esta clase
        data['saldo'] = data['total_debe'] - data['total_haber']
        
        # Optimización: Si no tiene saldo ni hijos con saldo, no lo retornes
        if data['saldo'] == 0 and not data['hijos']:
             return None

        return data

    def get(self, request, *args, **kwargs):
        empresa_id = request.empresa_id
        
        # --- Obtener filtros de fecha ---
        fecha_inicio_str = request.query_params.get('fecha_inicio', date(date.today().year, 1, 1).strftime('%Y-%m-%d'))
        fecha_fin_str = request.query_params.get('fecha_fin', date.today().strftime('%Y-%m-%d'))

        try:
            fecha_inicio = date.fromisoformat(fecha_inicio_str)
            fecha_fin = date.fromisoformat(fecha_fin_str)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Usar YYYY-MM-DD."}, status=400)

        # --- 1. Obtener saldos de cuentas (Clases 1, 2, 3) ---
        saldos_dict = self.get_saldos_cuentas_balance(empresa_id, fecha_fin)

        # --- 2. Calcular Resultado del Ejercicio (Clases 4, 5) ---
        resultado_ejercicio = self.get_resultado_del_ejercicio(empresa_id, fecha_inicio, fecha_fin)

        # --- 3. Construir el árbol de Balance (Clases 1, 2, 3) ---
        clases_raiz = self.get_clases_raiz(empresa_id)
        response_data = []
        
        patrimonio_index = -1
        
        for i, clase in enumerate(clases_raiz):
            data_clase = self.procesar_cuentas_recursivo(clase, saldos_dict)
            if data_clase: # Solo añadir si la clase tiene datos
                response_data.append(data_clase)
                if data_clase['codigo'] == 3: # Guardamos la posición del Patrimonio
                    patrimonio_index = len(response_data) - 1 # Usar el índice real
            
        # --- 4. Inyectar el Resultado del Ejercicio en el Patrimonio ---
        if patrimonio_index != -1 and resultado_ejercicio != 0:
            # Creamos el nodo "falso" para el resultado
            resultado_data = {
                "codigo": "3.R", # Código inventado para el resultado
                "nombre": "Resultado del Ejercicio (Utilidad/Pérdida)",
                "total_debe": Decimal(0) if resultado_ejercicio < 0 else resultado_ejercicio,
                "total_haber": abs(resultado_ejercicio) if resultado_ejercicio < 0 else Decimal(0),
                "saldo": resultado_ejercicio * -1, 
                "hijos": []
            }
            
            # Lo añadimos como hijo de Patrimonio
            response_data[patrimonio_index]['hijos'].append(resultado_data)
            
            # Actualizamos los totales de Patrimonio para incluir el resultado
            response_data[patrimonio_index]['total_debe'] += resultado_data['total_debe']
            response_data[patrimonio_index]['total_haber'] += resultado_data['total_haber']
            response_data[patrimonio_index]['saldo'] += resultado_data['saldo']

        return Response(response_data)


# Vista de PDF (Corregida para usar request.empresa_id)
class BalanceGeneralPDFView(BalanceGeneralView):

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
        if hasattr(request, 'empresa_id') and request.empresa_id:
            try:
                # Buscamos la empresa manualmente usando el ID
                empresa = Empresa.objects.get(id=request.empresa_id)
            except Empresa.DoesNotExist:
                pass # Dejar empresa=None si no se encuentra
        
        # 4. Generar el PDF
        pdf_context = {
            'empresa_nombre': empresa.nombre if empresa else 'Mi Empresa',
            'fecha_inicio': fecha_inicio_str,
            'fecha_fin': fecha_fin_str,
            'data': data
        }
        
        pdf = render_to_pdf_balance_general('reporte/pdf/balance_general.html', pdf_context)
        
        # 5. Devolver el PDF como respuesta
        return pdf