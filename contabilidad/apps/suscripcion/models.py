from django .db import models
import uuid
from django.conf import settings
from ..usuario.models.usuario import User

class Plan(models.Model):
    nombre = models.TextField()
    descripcion = models.TextField(default="", blank=True)
    codigo = models.TextField(unique=True)

    class Meta:
        db_table = "plan"

    def __str__(self):
        return f"{self.id} - {self.nombre} - {self.codigo}"
    
class Estado(models.Model):
    nombre = models.TextField()

    class Meta:
        db_table = "estado"

    def __str__(self):
        return f"{self.id} - {self.nombre}"
    
class Caracteristica(models.Model):
    cant_empresas = models.IntegerField(null=True, blank=True)
    cant_colab = models.IntegerField(null=True, blank=True)
    funcionalidad = models.TextField()
    codigo = models.TextField(unique=True)
    cant_consultas_ia = models.IntegerField(null=True, blank=True) #esto debe aparecer el el commit a mi sprint_2

    class Meta:
        db_table = "caracteristica"

    def __str__(self):
        return f"{self.id} - {self.codigo}"
    
class TipoPlan(models.Model):
    duracion_mes = models.IntegerField()
    precio = models.FloatField()
    codigo = models.TextField(unique=True)
    plan = models.ForeignKey("Plan", related_name='tipos', on_delete=models.CASCADE)
    caracteristica = models.ForeignKey("Caracteristica", related_name='tipos_plan', on_delete=models.CASCADE)

    class Meta:
        db_table = "tipo_plan"

    def __str__(self):
        return f"{self.id} - {self.codigo} - {self.plan.nombre} - {self.duracion_mes}"
    
class Suscripcion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    fecha_inicio = models.DateField(auto_now_add=True)
    fecha_fin = models.DateField(null=True, blank=True)
    codigo = models.TextField(default="", blank=True)
    dia_restante = models.IntegerField(default=0)
    empresa_disponible = models.IntegerField(default=0, null=True, blank=True)
    colab_disponible = models.IntegerField(default=0, null=True, blank=True)
    consultas_ia_restantes = models.IntegerField(null=True, blank=True, default=None) #esto debe aparecer el el commit a mi sprint_2
    estado = models.ForeignKey("Estado", related_name='suscripciones', default=3, on_delete=models.SET_DEFAULT)
    plan = models.ForeignKey("TipoPlan", related_name='suscripciones',on_delete=models.CASCADE)
    user = models.ForeignKey(User, related_name='suscripciones',on_delete=models.CASCADE)

    class Meta:
        db_table = "suscripcion"

    def __str__(self):
        return f"{self.id} - {self.fecha_inicio} - {self.plan.nombre} - {self.user.username}"
    
class Pago(models.Model):
    METODOS_PAGO = [
        ('tarjeta', 'Tarjeta'),
        ('qr','QR'),
    ]

    ESTADOS_PAGO = [
        ('pendiente', 'Pendiente'),
        ('pagado','pagado'),
        ('fallido','Fallido'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    monto = models.FloatField()
    fecha_pago = models.DateField(auto_now_add=True)
    metodos_pago = models.CharField(max_length=50, choices=METODOS_PAGO)
    estado_pago = models.CharField(max_length=50, choices=ESTADOS_PAGO, default='pendiente')
    codigo_pago = models.TextField(default="", blank=True)
    id_transaccion_externa = models.TextField(default="", blank=True)
    suscripcion = models.ForeignKey("Suscripcion", related_name='pagos',on_delete=models.CASCADE)
    
    class Meta:
        db_table = "pago"
    
    def __str__(self):
        return f"{self.codigo_pago} - {self.estado_pago} - {self.monto}"