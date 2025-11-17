#!/bin/sh

# Salir inmediatamente si un comando falla
set -e

# Ejecutar las migraciones
echo "Aplicando migraciones de la base de datos..."
python manage.py migrate

# Iniciar el servidor Gunicorn
echo "Iniciando servidor Gunicorn..."
exec gunicorn --bind 0.0.0.0:8080 contabilidad.wsgi:application --timeout 120