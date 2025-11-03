from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.response import Response
from ..models import Empresa, UserEmpresa
from django.db.models import Q
from ..serializers import (EmpresaCreateSerializer,
                           EmpresaDetailSerializer,
                           EmpresaListSerializer)
from django.db import transaction
from rest_framework.exceptions import PermissionDenied
from contabilidad.apps.suscripcion.models import Suscripcion, Estado

class EmpresaViewSet(viewsets.ModelViewSet):
    queryset = Empresa.objects.all()
    serializer_class = EmpresaListSerializer
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action == 'list':
            return EmpresaListSerializer
        elif self.action in ['create','update','partial_update']:
            return EmpresaCreateSerializer
        elif self.action in ['retrieve','destroy']:
            return EmpresaDetailSerializer
        return super().get_serializer_class()
    
    @transaction.atomic # Asegura que la verificación y creación/decremento sean atómicos
    def perform_create(self, serializer):
        usuario = self.request.user
        try:
            # Obtener estado activo y la suscripción activa
            estado_activo = Estado.objects.get(nombre='activo')
            suscripcion = Suscripcion.objects.get(user=usuario, estado=estado_activo)
        except (Estado.DoesNotExist, Suscripcion.DoesNotExist):
            raise PermissionDenied("No tienes una suscripción activa para crear empresas.")

        # Verificar límite de empresas (None significa ilimitado)
        if suscripcion.empresa_disponible is not None:
            if suscripcion.empresa_disponible <= 0:
                raise PermissionDenied("Has alcanzado el límite de empresas para tu plan.")
            # Decrementar el contador
            suscripcion.empresa_disponible -= 1
            suscripcion.save() # Guardar el cambio en la suscripción

        # Continuar con la creación normal de la empresa (DRF llama a serializer.save())
        # El serializer ya se encarga de crear UserEmpresa y RolEmpresa
        serializer.save() 

    # El método create ahora solo llama a super().create o se puede eliminar si perform_create es suficiente
    # def create(self, request, *args, **kwargs):
    #     # ... (La lógica ahora está en perform_create)
    #     return super().create(request, *args, **kwargs)
    
    @action(detail=False, methods=['get'])
    def mis_empresas(self, request):
        user = request.user
        # Mostrar empresas donde el usuario tiene la relación aceptada
        # O mostrar empresas donde el usuario es administrador (las que creó)
        user_empresas = UserEmpresa.objects.filter(usuario=user).filter(Q(estado='ACEPTADA') | Q(roles__nombre='admin')).distinct()
        empresas = [ue.empresa for ue in user_empresas]
        serializer = EmpresaListSerializer(empresas, many=True)

        return Response(serializer.data)
