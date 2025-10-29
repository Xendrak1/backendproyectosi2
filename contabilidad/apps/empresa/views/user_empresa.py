from rest_framework import viewsets
from ..models import UserEmpresa
from ..serializers import (UserEmpresaCreateSerializer,
                           UserEmpresaDetailSerializer,
                           UserEmpresaListSerializer)
from django.db import transaction
from rest_framework.exceptions import PermissionDenied
from contabilidad.apps.suscripcion.models import Suscripcion, Estado

class UserEmpresaViewSet(viewsets.ModelViewSet):
    queryset = UserEmpresa.objects.all()
    serializer_class = UserEmpresaListSerializer
    def get_object(self):
        obj = super().get_object()
        print("ID solicitado:", self.kwargs["pk"])
        print("Queryset actual:", self.get_queryset())
        return obj
    def get_serializer_class(self):
        if self.action == 'list':
            return UserEmpresaListSerializer
        elif self.action in ['create','update','partial_update']:
            return UserEmpresaCreateSerializer
        elif self.action in ['retrieve','destroy']:
            return UserEmpresaDetailSerializer
        return super().get_serializer_class()
    
    def get_queryset(self):
        request = self.request

        # Por defecto, tomar la empresa del token
        empresa_id = request.auth.get('empresa')

        queryset = UserEmpresa.objects.filter(empresa=empresa_id).distinct()

        if self.action == "list" :
            # Solo usuarios normales, excluir roles admin
            queryset = queryset.exclude(roles__nombre='admin')

        return queryset
    
    @transaction.atomic
    def perform_create(self, serializer):
        usuario_creador = self.request.user # El usuario que está añadiendo al colaborador
        try:
            estado_activo = Estado.objects.get(nombre='activo')
            suscripcion = Suscripcion.objects.get(user=usuario_creador, estado=estado_activo)
        except (Estado.DoesNotExist, Suscripcion.DoesNotExist):
            raise PermissionDenied("No tienes una suscripción activa para añadir colaboradores.")

        # Verificar límite de colaboradores (None es ilimitado)
        if suscripcion.colab_disponible is not None:
            # Contar colaboradores actuales (excluyendo al admin/creador si es necesario,
            # pero usualmente el límite es sobre el total de usuarios en la empresa)
            empresa_id = self.request.auth.get('empresa')
            #colaboradores_actuales = UserEmpresa.objects.filter(empresa_id=empresa_id).count()

            # Comparar con el límite inicial del plan (almacenado en suscripcion)
            # O podrías comparar directamente con suscripcion.colab_disponible si lo decrementas
            #limite_colabs = suscripcion.plan.caracteristica.cant_colab
            #if colaboradores_actuales + 1 > limite_colabs:
            #     raise PermissionDenied("Has alcanzado el límite de colaboradores para tu plan.")

            # Decrementar contador si usas esa lógica (opcional si comparas con el total)
            if suscripcion.colab_disponible <= 0:
                raise PermissionDenied("Has alcanzado el límite de colaboradores para tu plan.")
            suscripcion.colab_disponible -= 1
            suscripcion.save()

        # Continuar con la creación normal del UserEmpresa
        # El serializer necesita el 'request' para obtener la empresa del token
        serializer.save()

