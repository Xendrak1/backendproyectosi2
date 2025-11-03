from django.db import models
from ...usuario.models.usuario import User
from .empresa import Empresa
from .custom import Custom

        
class UserEmpresa(models.Model):
    usuario = models.ForeignKey(User, on_delete=models.CASCADE)
    empresa = models.ForeignKey(Empresa, on_delete=models.CASCADE, related_name="user_empresas")
    custom = models.ForeignKey(Custom, on_delete=models.SET_NULL, null=True, blank=True)
    texto_tipo = models.CharField(max_length=50, null=True, blank=True)
    texto_tamano = models.CharField(max_length=50, null=True, blank=True)
    ESTADO_CHOICES = [
        ('PENDIENTE', 'PENDIENTE'),
        ('ACEPTADA', 'ACEPTADA'),
        ('RECHAZADA', 'RECHAZADA'),
    ]
    estado = models.CharField(max_length=20, choices=ESTADO_CHOICES, default='PENDIENTE')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  
    class Meta:
        db_table = "user_empresa"  
        unique_together = ('usuario', 'empresa')
    
    def __str__(self):
        return f"{self.usuario.username} - {self.empresa.nombre}"
        