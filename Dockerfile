# Imagen base 5/11/2025
FROM python:3.11-slim

# Configuración Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Carpeta de trabajo
WORKDIR /app

# Instalar dependencias del sistema necesarias para psycopg2 y compilación
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copiar dependencias e instalarlas
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del proyecto
COPY . /app

# Exponer el puerto
EXPOSE 8080

# Comando para arrancar Django con Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "contabilidad.wsgi:application", "--timeout", "120"]