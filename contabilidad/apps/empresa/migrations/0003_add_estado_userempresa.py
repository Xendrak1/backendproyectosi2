from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('empresa', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='userempresa',
            name='estado',
            field=models.CharField(choices=[('PENDIENTE', 'PENDIENTE'), ('ACEPTADA', 'ACEPTADA'), ('RECHAZADA', 'RECHAZADA')], default='PENDIENTE', max_length=20),
        ),
    ]
