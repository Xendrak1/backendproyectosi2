from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.shortcuts import get_object_or_404
from django.db import transaction
from rest_framework.exceptions import PermissionDenied
from contabilidad.apps.suscripcion.models import Suscripcion, Estado

from .services import IAReporteService
from .serializers import (
    SolicitudReporteSerializer,
    ReporteResponseSerializer
)
from contabilidad.apps.empresa.models import Empresa
from contabilidad.apps.empresa.models.user_empresa import UserEmpresa


@api_view(['POST'])

@permission_classes([IsAuthenticated])
@transaction.atomic
def generar_reporte_ia(request):
    """
    Endpoint para generar reportes usando IA basado en texto natural.
    
    Recibe una solicitud en lenguaje natural y devuelve el reporte correspondiente
    basado en los datos del usuario autenticado y su empresa.
    """
    try:
        # Validar datos de entrada
        serializer = SolicitudReporteSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'error': 'Datos de entrada inválidos',
                'detalles': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)
        
        texto_solicitud = serializer.validated_data['texto_solicitud']
        usuario = request.user

        # --- VERIFICACIÓN Y DECREMENTO DE LÍMITE IA ---
        try:
            estado_activo = Estado.objects.get(nombre='activo')
            suscripcion = Suscripcion.objects.select_for_update().get(user=usuario, estado=estado_activo) # select_for_update para bloqueo
        except (Estado.DoesNotExist, Suscripcion.DoesNotExist):
            raise PermissionDenied("No tienes una suscripción activa.")

        consultas_restantes = suscripcion.consultas_ia_restantes

        if consultas_restantes == 0: # Si es 0, el límite se alcanzó
             return Response({
                'success': False,
                'error': 'Has alcanzado el límite de consultas IA para tu plan.'
            }, status=status.HTTP_403_FORBIDDEN) # 403 Forbidden
        elif consultas_restantes is None: # Si es None, es ilimitado
            pass # No hacer nada, continuar
        else: # Si es > 0, decrementar
            suscripcion.consultas_ia_restantes -= 1
            suscripcion.save(update_fields=['consultas_ia_restantes']) # Guardar solo este campo
        # --- FIN VERIFICACIÓN IA ---

        # Obtener la empresa del usuario
        try:
            empresa_id = request.auth.get('empresa') 
            user_empresa = UserEmpresa.objects.get(usuario=usuario, empresa=empresa_id)
            empresa = Empresa.objects.get(id=empresa_id)
        except UserEmpresa.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Usuario no está asociado a ninguna empresa'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Generar reporte usando IA
        servicio_ia = IAReporteService()
        resultado = servicio_ia.procesar_solicitud_reporte(
            texto_solicitud=texto_solicitud,
            usuario=usuario,
            empresa=empresa
        )
        print("eest es el ereuslta",resultado)
        # Serializar respuesta
        response_serializer = ReporteResponseSerializer(resultado)
        
        if resultado['success']:
            return Response(response_serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(response_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        return Response({
            'success': False,
            'error': f'Error interno del servidor: {str(e)}',
            'solicitud_original': request.data.get('texto_solicitud', '')
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def obtener_ejemplos_solicitudes(request):
    """
    Endpoint para obtener ejemplos de solicitudes que puede procesar la IA.
    """
    ejemplos = [
        {
            'categoria': 'Balance General',
            'ejemplos': [
                'Genera un balance general al 31 de diciembre',
                'Necesito el balance general de este año',
                'Muéstrame la situación financiera actual'
            ]
        },
        {
            'categoria': 'Estado de Resultados',
            'ejemplos': [
                'Genera el estado de resultados del último trimestre',
                'Necesito ver las ganancias y pérdidas de este año',
                'Muéstrame la utilidad del último mes'
            ]
        },
        {
            'categoria': 'Libro Mayor',
            'ejemplos': [
                'Genera el libro mayor de la cuenta 111 (Efectivo)',
                'Necesito el mayor de todas las cuentas de activos',
                'Muéstrame el mayor de las cuentas de gastos'
            ]
        },
        {
            'categoria': 'Libro Diario',
            'ejemplos': [
                'Genera el libro diario del último mes',
                'Necesito ver todos los asientos de este año',
                'Muéstrame los asientos del último trimestre'
            ]
        },
        {
            'categoria': 'Análisis Específico',
            'ejemplos': [
                'Analiza el saldo de las cuentas por cobrar',
                'Muéstrame el movimiento de efectivo',
                'Necesito un análisis de los gastos de administración'
            ]
        }
    ]
    
    return Response({
        'ejemplos': ejemplos,
        'instrucciones': [
            'Puedes usar lenguaje natural para solicitar reportes',
            'Menciona fechas específicas o períodos como "último mes", "este año"',
            'Especifica cuentas por código o nombre',
            'Pide análisis específicos de saldos o movimientos'
        ]
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def obtener_informacion_empresa(request):
    """
    Endpoint para obtener información de la empresa del usuario para contexto.
    """
    try:
        usuario = request.user
        user_empresa = UserEmpresa.objects.get(usuario=usuario)
        empresa = user_empresa.empresa
        
        # Obtener información básica de la empresa
        from contabilidad.apps.gestion_cuenta.models import Cuenta, ClaseCuenta
        
        cuentas_activas = Cuenta.objects.filter(
            empresa=empresa,
            estado='ACTIVO'
        ).count()
        
        clases_cuentas = ClaseCuenta.objects.filter(empresa=empresa).count()
        
        # Obtener algunas cuentas principales
        cuentas_principales = Cuenta.objects.filter(
            empresa=empresa,
            estado='ACTIVO'
        ).select_related('clase_cuenta')[:10]
        
        cuentas_info = []
        for cuenta in cuentas_principales:
            cuentas_info.append({
                'codigo': cuenta.codigo,
                'nombre': cuenta.nombre,
                'clase': cuenta.clase_cuenta.nombre if cuenta.clase_cuenta else 'Sin clase'
            })
        
        return Response({
            'empresa': {
                'nombre': empresa.nombre,
                'nit': empresa.nit
            },
            'estadisticas': {
                'total_cuentas': cuentas_activas,
                'total_clases': clases_cuentas
            },
            'cuentas_principales': cuentas_info
        }, status=status.HTTP_200_OK)
        
    except UserEmpresa.DoesNotExist:
        return Response({
            'error': 'Usuario no está asociado a ninguna empresa'
        }, status=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        return Response({
            'error': f'Error al obtener información: {str(e)}'
        }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
