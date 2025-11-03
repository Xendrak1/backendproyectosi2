from rest_framework import serializers
from ..models import UserEmpresa, Custom
from ...usuario.models import User
from ...usuario.serializers import UsuarioDetailSerializer
from .rol import RolEmpresaListSerializer
from django.core import signing
from django.core.mail import send_mail
from django.conf import settings
from django.urls import reverse
from django.db import transaction


class CustomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Custom
        fields = ["id", "nombre", "color_primario", "color_secundario", "color_terciario"]


class UserEmpresaCreateSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(write_only=True, required=True)
    texto_tipo = serializers.CharField(required=False)
    texto_tamano = serializers.CharField(required=False)
    custom = serializers.PrimaryKeyRelatedField(queryset=Custom.objects.all(), required=False)

    class Meta:
        model = UserEmpresa
        fields = ["email", "custom", "texto_tipo", "texto_tamano"]

    def validate_email(self, value):
        try:
            usuario = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError("Usuario no existe")

        # Asegurarse de que esté verificado
        if not getattr(usuario, "verified", False):
            raise serializers.ValidationError("Usuario no verificado")

        return usuario

    def create(self, validated_data):
        request = self.context.get("request")
        empresa_id = None
        if request is not None:
            try:
                empresa_id = request.auth.get("empresa")
            except Exception:
                empresa_id = None

        user = validated_data.pop("email")  # objeto User retornado por validate_email

        from ..models import Empresa
        if not empresa_id:
            raise serializers.ValidationError("Empresa no especificada en la petición")

        try:
            empresa = Empresa.objects.get(pk=empresa_id)
        except Empresa.DoesNotExist:
            raise serializers.ValidationError("Empresa no encontrada")

        if UserEmpresa.objects.filter(usuario=user, empresa=empresa).exists():
            raise serializers.ValidationError("El usuario ya es colaborador de esta empresa")

        custom = validated_data.get("custom") or Custom.objects.filter(nombre="verde").first()

        try:
            with transaction.atomic():
                user_empresa = UserEmpresa.objects.create(
                    usuario=user,
                    empresa=empresa,
                    custom=custom,
                    texto_tipo="INVITACION_PENDIENTE",
                    estado="PENDIENTE",
                )

                # Generar token y enviar correo (no interrumpe si falla el envío)
                try:
                    token = signing.dumps({"user_id": user.id, "empresa_id": str(empresa.id)}, salt="empresa-invite")
                    relative = reverse("empresa-invitacion-accept")
                    path = f"{relative}?token={token}"
                    public = getattr(settings, "DJANGO_PUBLIC_URL", "")
                    if public:
                        accept_url = f"{public}{path}"
                    else:
                        if request is not None:
                            accept_url = request.build_absolute_uri(path)
                        else:
                            accept_url = path

                    subject = f"Invitación a colaborar en {empresa.nombre}"
                    html_body = f"<p>Hola {user.persona.nombre},</p>\n<p>Has sido invitado a colaborar en la empresa <strong>{empresa.nombre}</strong>. Haz clic en el siguiente enlace para aceptar la invitación:</p>\n<p><a href=\"{accept_url}\">Aceptar invitación</a></p>"
                    send_mail(subject, "", from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None), recipient_list=[user.email], html_message=html_body)
                except Exception:
                    pass

                return user_empresa
        except Exception as e:
            raise serializers.ValidationError({"detail": "No se pudo crear la invitación", "error": str(e)})


class UserEmpresaListSerializer(serializers.ModelSerializer):
    usuario = UsuarioDetailSerializer()
    roles = RolEmpresaListSerializer(many=True, read_only=True)

    class Meta:
        model = UserEmpresa
        fields = ["id", "usuario", "roles"]


class UserEmpresaDetailSerializer(serializers.ModelSerializer):
    roles = RolEmpresaListSerializer(many=True, read_only=True)
    custom = CustomSerializer(read_only=True)

    class Meta:
        model = UserEmpresa
        fields = ["id", "usuario", "empresa", "roles", "custom", "texto_tipo", "texto_tamano"]