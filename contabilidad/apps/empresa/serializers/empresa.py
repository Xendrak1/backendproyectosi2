from rest_framework import serializers
from ..models import Empresa,RolEmpresa,UserEmpresa,Custom
from .user_empresa import UserEmpresaListSerializer

class EmpresaCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empresa
        fields = [ 'nombre','nit']
        
    def create(self, validated_data):
        usuario = self.context['request'].user
        empresa = Empresa.objects.create(**validated_data)
        custom = Custom.objects.get(nombre='verde')
        rol = RolEmpresa.objects.get(nombre='admin',empresa=empresa)
        # El creador de la empresa se marca como ACEPTADA de inmediato
        user_empresa = UserEmpresa.objects.create(usuario=usuario, empresa=empresa, custom=custom, estado='ACEPTADA')
        user_empresa.roles.add(rol)
        return empresa
    
class EmpresaListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Empresa
        fields = ['id','nombre']

class EmpresaDetailSerializer(serializers.ModelSerializer):
    usuarios = UserEmpresaListSerializer(many=True, read_only=True,source="user_empresas")
    
    class Meta:
        model = Empresa
        fields = ['id','nombre','nit','usuarios']
