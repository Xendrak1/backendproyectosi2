from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from django.utils.dateformat import DateFormat
from datetime import date
from .models import Suscripcion, Plan, Estado, TipoPlan, Caracteristica, Pago


# lectura
class EstadoSerializer(serializers.ModelSerializer):
    class Meta:
        model = Estado
        fields = ['nombre']

class PlanSeralizer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = ['nombre', 'descripcion', 'codigo']

class CaracteristicaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Caracteristica
        fields = ['cant_empresas', 'cant_colab', 'funcionalidad', 'cant_consultas_ia', 'codigo']

class TipoPlanSerializer(serializers.ModelSerializer):
    plan = PlanSeralizer(read_only=True)
    caracteristica = CaracteristicaSerializer(read_only=True)
    class Meta:
        model = TipoPlan
        fields = ['id','duracion_mes', 'precio', 'codigo', 'plan', 'caracteristica']
    
class SuscripcionDetailSerializer(serializers.ModelSerializer):
    estado = EstadoSerializer(read_only=True)
    plan = TipoPlanSerializer(read_only=True)
    class Meta:
        model = Suscripcion
        fields = ["id", "fecha_inicio", "fecha_fin", "codigo", "dia_restante", "empresa_disponible", "colab_disponible", "consultas_ia_restantes", "estado", "plan", "user"]

class PaymentRequestSerializer(serializers.Serializer):
    tipo_plan_id = serializers.IntegerField() # Cambiado a IntegerField para coincidir con BigAutoField
    card_number = serializers.CharField(max_length=16, write_only=True)
    card_expiry = serializers.CharField(max_length=5, write_only=True)
    card_cvv = serializers.CharField(max_length=4, write_only=True)
    
    # Campo para devolver la instancia del plan y usarlo en la vista
    tipo_plan = TipoPlanSerializer(read_only=True)

    def validate_tipo_plan_id(self, value):
        try:
            tipo_plan = TipoPlan.objects.select_related('plan', 'caracteristica').get(id=value)
            return tipo_plan
        except TipoPlan.DoesNotExist:
            raise ValidationError("El ID del plan proporcionado no es válido.")

    def validate(self, data):
        # El campo tipo_plan_id ya fue validado y ahora es el objeto TipoPlan
        data['tipo_plan'] = data.pop('tipo_plan_id') 

        # Simulación básica de validación de tarjeta (solo si no es gratuito)
        if data['tipo_plan'].precio > 0:
            if not data.get('card_number') or len(data['card_number']) < 16:
                 raise ValidationError({"card_number": "Número de tarjeta inválido."})
            # Aquí podrías añadir más validaciones de CVV o expiración.
            
        return data
    
class SubscriptionSuccessSerializer(serializers.ModelSerializer):
    plan_nombre = serializers.SerializerMethodField()
    fecha_fin_formateada = serializers.SerializerMethodField()
    
    class Meta:
        model = Suscripcion
        fields = ['id', 'fecha_inicio', 'fecha_fin', 'codigo', 'plan_nombre', 'fecha_fin_formateada']

    def get_plan_nombre(self, obj):
        # Accedemos al nombre del plan a través de la relación TipoPlan
        return obj.plan.plan.nombre
    
    def get_fecha_fin_formateada(self, obj):
        if obj.fecha_fin:
            # Formatea la fecha de fin a un formato legible en español
            # 'd \d\e F \d\e Y' -> 20 de Octubre de 2025
            return DateFormat(obj.fecha_fin).format('d \d\e F \d\e Y')
        return "Indefinida"