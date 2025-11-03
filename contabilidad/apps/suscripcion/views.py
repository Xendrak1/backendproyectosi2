from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from django.db import transaction
from django.conf import settings
from decouple import config
from datetime import date, timedelta
import uuid
import requests
import json # <-- NECESARIO PARA json.dumps
from .models import Suscripcion, Estado, TipoPlan, Pago
from .serializers import (
    SuscripcionDetailSerializer, 
    TipoPlanSerializer, 
    PaymentRequestSerializer, 
    SubscriptionSuccessSerializer
)

class SuscripcionViewSet(viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = SuscripcionDetailSerializer

    def get_queryset(self):
        return Suscripcion.objects.filter(user=self.request.user)

    @action(detail=False, methods=['get'], url_path='activa')
    def get_suscripcion_activa(self, request):
        """
        Endpoint: GET /suscripcion/activa/
        Devuelve la suscripción activa o los planes disponibles (con 404).
        """
        try:
            estado_activo = Estado.objects.get(nombre='activo')
        except Estado.DoesNotExist:
            return Response({"detail": "Error de configuración: Estado 'activo' no encontrado."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        suscripcion = self.get_queryset().filter(estado=estado_activo).order_by('-fecha_inicio').first()

        if suscripcion:
            serializer = self.get_serializer(suscripcion)
            return Response(serializer.data, status=status.HTTP_200_OK)
        
        planes_disponibles = TipoPlan.objects.all().select_related('plan', 'caracteristica')
        serializer = TipoPlanSerializer(planes_disponibles, many=True)
        
        return Response({
            "detail": "No se encontró suscripción activa.",
            "planes_disponibles": serializer.data
        }, status=status.HTTP_404_NOT_FOUND)

    @action(detail=False, methods=['post'], url_path='confirmar_compra')
    def create_subscription_and_pay(self, request):
        """
        Endpoint: POST /suscripcion/confirmar_compra/
        Maneja planes gratuitos (activación directa) o planes de pago (Libélula).
        """
        serializer = PaymentRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        user = request.user
        tipo_plan = serializer.validated_data['tipo_plan']
        caracteristica = tipo_plan.caracteristica
        # Lógica de cálculo de fechas (Común a ambos flujos)
        if tipo_plan.duracion_mes > 0:
            fecha_fin_deuda = date.today() + timedelta(days=tipo_plan.duracion_mes * 30)
            dias_restantes = tipo_plan.duracion_mes * 30
        else:
            fecha_fin_deuda = date.today() + timedelta(days=36500) 
            dias_restantes = 36500
        #iniciar valores de los contadores
        empresa_inicial = caracteristica.cant_empresas
        colab_inicial = caracteristica.cant_colab
        ia_inicial = caracteristica.cant_consultas_ia

        #FLUJO 1: PLAN GRATUITO (Activar directamente)
        if tipo_plan.precio == 0:
            print("Procesando plan gratuito...")
            print(f"precio tipo_plan: {tipo_plan.precio}")
            try:
                with transaction.atomic():
                    estado_activo = Estado.objects.get(nombre='activo')
                    #estado_nulo = Estado.objects.get(nombre='nulo')
                    
                    # Desactivar suscripciones anteriores
                    #Suscripcion.objects.filter(user=user, estado=estado_activo).update(estado=estado_nulo)
                    
                    suscripcion = Suscripcion.objects.create(
                        user=user,
                        estado=estado_activo,
                        plan=tipo_plan, 
                        fecha_inicio=date.today(),
                        fecha_fin=fecha_fin_deuda,
                        codigo=f"SUB-GRATIS-{str(user.id)}", 
                        dia_restante=dias_restantes,
                        empresa_disponible=empresa_inicial,
                        colab_disponible=colab_inicial,
                        consultas_ia_restantes=ia_inicial
                    )
                    
                    return Response(SubscriptionSuccessSerializer(suscripcion).data, status=status.HTTP_201_CREATED)

            except Estado.DoesNotExist:
                return Response({"detail": "Error de configuración: Los estados 'activo' o 'nulo' son requeridos en la DB."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            except Exception as e:
                print(f"Error procesando plan gratuito: {e}")
                return Response({"detail": f"Error interno al activar plan gratuito: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # FLUJO 2: PLAN DE PAGO (Llamada a Libélula)
        # Preparar URLs de Callback y Retorno
        identificador_deuda = f"SUB-{str(user.id).zfill(8)}-{uuid.uuid4().hex[:8]}" 
        
        callback_url = f"{settings.DJANGO_PUBLIC_URL}/suscripcion/pago_exitoso" #url del dominio del backend
        return_url = f"https://contafrontoficial-393159630636.northamerica-south1.run.app/librovivo/darshboard" #url del dominio del frontend
        
        # CORRECCIÓN CLAVE: El campo concepto debe ser una string válida y limpia
        concepto_item = f"Suscripción {tipo_plan.plan.nombre} {tipo_plan.duracion_mes} mes(es)"
        
        lineas_detalle_deuda = [
            { 
                "concepto": concepto_item.strip(), # Aplicamos .strip() y aseguramos la string
                "cantidad": 1, 
                "costo_unitario": float(tipo_plan.precio), 
                "descuento_unitario": 0
            }
        ]

        libelula_payload = {
            "appkey": settings.LIBELULA_APPKEY,
            "email_cliente": user.email, 
            "identificador_deuda": identificador_deuda, 
            "fecha_vencimiento": (date.today() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),
            "descripcion": f"Pago de suscripción {tipo_plan.plan.nombre}",
            "callback_url": callback_url, 
            "url_retorno": return_url,
            "nombre_cliente": user.persona.nombre,
            "apellido_cliente": user.persona.apellido,
            "ci": user.persona.ci or "",
            "razon_social": f"{user.persona.nombre} {user.persona.apellido}",
            "nit": user.persona.ci or "99002",
            "emite_factura": True, 
            "moneda": "BOB",
        }

        # Añadir las líneas de detalle en el formato esperado por Libélula
        for i, item in enumerate(lineas_detalle_deuda):
            libelula_payload[f"lineas_detalle_deuda[{i}].concepto"] = item["concepto"]
            libelula_payload[f"lineas_detalle_deuda[{i}].cantidad"] = item["cantidad"]
            libelula_payload[f"lineas_detalle_deuda[{i}].costo_unitario"] = item["costo_unitario"]
            libelula_payload[f"lineas_detalle_deuda[{i}].descuento_unitario"] = item["descuento_unitario"]

        # 2. Llamar a la API de Libélula
        LIBELULA_ENDPOINT = f"{settings.LIBELULA_URL}/rest/deuda/registrar"
        
        try:
            response = requests.post(LIBELULA_ENDPOINT, data=libelula_payload)
            response.raise_for_status() 

            libelula_data = response.json()

            if libelula_data.get("error") == 0 and "url_pasarela_pagos" in libelula_data:
                # Éxito de registro de deuda: Guardar como PENDIENTE
                with transaction.atomic():
                    estado_pendiente = Estado.objects.get(nombre='pendiente')
                    Suscripcion.objects.create(
                        user=user,
                        estado=estado_pendiente,
                        plan=tipo_plan, 
                        fecha_inicio=date.today(),
                        fecha_fin=fecha_fin_deuda,
                        codigo=identificador_deuda, 
                        dia_restante=dias_restantes,
                        empresa_disponible=empresa_inicial,
                        colab_disponible=colab_inicial,
                        consultas_ia_restantes=ia_inicial
                    )
                
                return Response({
                    "url_pasarela_pagos": libelula_data["url_pasarela_pagos"],
                    "id_transaccion": libelula_data["id_transaccion"]
                }, status=status.HTTP_200_OK)
            else:
                # Falla de Libélula (error != 0)
                return Response({
                    "detail": libelula_data.get("mensaje", "Error desconocido de Libélula al registrar la deuda.")
                }, status=status.HTTP_400_BAD_REQUEST)

        except requests.exceptions.RequestException as e:
            print(f"Error de conexión con Libélula: {e}")
            return Response({"detail": f"Error de conexión con la pasarela de pagos: {e}"}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        except Estado.DoesNotExist:
            return Response({"detail": "Estado 'pendiente' no encontrado. Ejecute los seeders."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PagoExitosoCallback(APIView):
    # Permite acceso sin autenticación (ya que Libélula te llama directamente)
    permission_classes = [AllowAny] 
    
    @transaction.atomic
    def get(self, request):
        """
        Servicio PAGO EXITOSO (Callback de Libélula).
        """
        transaction_id = request.query_params.get('transaction_id')
        
        if not transaction_id:
            return Response({"detail": "Falta el identificador de transacción."}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            # 1. Buscar la suscripción pendiente usando el identificador_deuda como código
            suscripcion = Suscripcion.objects.get(codigo=transaction_id)
            
            # 2. Obtener estados y verificar
            estado_activo = Estado.objects.get(nombre='activo')
            if suscripcion.estado == estado_activo:
                return Response({"detail": "Suscripción ya estaba activa."}, status=status.HTTP_200_OK)
            
            # 3. Activar Suscripción
            tipo_plan = suscripcion.plan
            caracteristica = tipo_plan.caracteristica
            fecha_inicio_real = date.today() # Usar la fecha actual como inicio real
            if tipo_plan.duracion_mes > 0:
                fecha_fin_real = fecha_inicio_real + timedelta(days=tipo_plan.duracion_mes * 30)
                dias_restantes_real = (fecha_fin_real - fecha_inicio_real).days
            else: # Plan "ilimitado" en tiempo
                fecha_fin_real = fecha_inicio_real + timedelta(days=36500)
                dias_restantes_real = 36500

            suscripcion.estado = estado_activo
            suscripcion.fecha_inicio = fecha_inicio_real # Actualizar fecha inicio
            suscripcion.fecha_fin = fecha_fin_real     # Actualizar fecha fin
            suscripcion.dia_restante = dias_restantes_real # Actualizar días
            # --- CONFIRMAR/ACTUALIZAR CONTADORES ---
            suscripcion.empresa_disponible = caracteristica.cant_empresas
            suscripcion.colab_disponible = caracteristica.cant_colab
            suscripcion.consultas_ia_restantes = caracteristica.cant_consultas_ia
            # --------------------------------------

            estado_pagado = 'pagado'
            suscripcion.estado = estado_activo 
            suscripcion.save()
            # 4. Registrar el Pago
            metodo_pago = 'tarjeta' # Valor por defecto
            
            Pago.objects.create(
                suscripcion=suscripcion,
                monto=suscripcion.plan.precio,
                fecha_pago=date.today(),
                metodos_pago=metodo_pago,
                estado_pago=estado_pagado, 
                codigo_pago=transaction_id,
                id_transaccion_externa=request.query_params.get('invoice_id', 'LIBELULA_WEB')
            )
            
            return Response({"detail": "Pago confirmado y suscripción activada."}, status=status.HTTP_200_OK)

        except Suscripcion.DoesNotExist:
            return Response({"detail": "Deuda no encontrada en el sistema."}, status=status.HTTP_404_NOT_FOUND)
        except Estado.DoesNotExist:
            return Response({"detail": "Error de configuración de estados."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        except Exception as e:
            print(f"Error procesando callback de Libélula: {e}")
            return Response({"detail": "Error interno del servidor al procesar el pago."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)