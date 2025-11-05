from django.db import models
from ...gestion_cuenta.models.cuenta import Cuenta
from .asiento_contable import AsientoContable
import uuid

class Movimiento(models.Model):
    class Meta:
        db_table = "movimiento"
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    referencia = models.CharField(max_length=100,null=True,blank=True)
    debe = models.DecimalField(max_digits=10,decimal_places=3)
    haber = models.DecimalField(max_digits=10,decimal_places=3)
    cuenta = models.ForeignKey(
        Cuenta,
        on_delete=models.CASCADE,
        related_name="movimientos"
    )
    asiento_contable = models.ForeignKey(
        AsientoContable,
        on_delete=models.CASCADE,
        related_name="movimientos"
    )
    
    def __str__(self):
        return f"Movimiento {self.cuenta.codigo} - {self.referencia}"