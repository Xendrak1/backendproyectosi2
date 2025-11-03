"""
Utilidad para validar Google reCAPTCHA v2

CONFIGURACION:
- En settings.py debe estar configurado: RECAPTCHA_SECRET_KEY
- El frontend debe enviar 'recaptcha_token' en el request
- Para obtener las claves: https://www.google.com/recaptcha/admin

USO:
    from contabilidad.apps.utils.recaptcha import validate_recaptcha
    
    def post(self, request):
        recaptcha_token = request.data.get('recaptcha_token')
        validate_recaptcha(recaptcha_token)
        # ... resto del codigo
"""
import requests
from django.conf import settings
from rest_framework.exceptions import ValidationError


def validate_recaptcha(recaptcha_token):
    """
    Valida el token de reCAPTCHA v2 con Google.
    
    Args:
        recaptcha_token (str): Token recibido del frontend
        
    Returns:
        bool: True si la validacion es exitosa
        
    Raises:
        ValidationError: Si la validacion falla
    """
    if not recaptcha_token:
        raise ValidationError({
            'recaptcha': 'El token de reCAPTCHA es requerido'
        })
    
    # Obtener la secret key desde settings
    recaptcha_secret = getattr(settings, 'RECAPTCHA_SECRET_KEY', None)
    
    if not recaptcha_secret:
        # En desarrollo, si no hay secret key configurada, permitir el acceso
        if settings.DEBUG:
            print("WARNING: RECAPTCHA_SECRET_KEY no configurada. Saltando validacion en DEBUG mode.")
            return True
        raise ValidationError({
            'recaptcha': 'reCAPTCHA no esta configurado correctamente en el servidor'
        })
    
    # Hacer la peticion a Google para verificar el token
    url = 'https://www.google.com/recaptcha/api/siteverify'
    data = {
        'secret': recaptcha_secret,
        'response': recaptcha_token
    }
    
    try:
        response = requests.post(url, data=data, timeout=10)
        result = response.json()
        
        if result.get('success'):
            return True
        else:
            # Log de errores para debugging
            error_codes = result.get('error-codes', [])
            print(f"reCAPTCHA validation failed: {error_codes}")
            
            raise ValidationError({
                'recaptcha': 'Validacion de reCAPTCHA fallida. Por favor, intenta nuevamente.'
            })
            
    except requests.RequestException as e:
        print(f"Error connecting to reCAPTCHA service: {str(e)}")
        raise ValidationError({
            'recaptcha': 'Error al validar reCAPTCHA. Por favor, intenta nuevamente.'
        })

