from rest_framework import serializers


class EstadoResultadosCuentaSerializer(serializers.Serializer):
    codigo = serializers.IntegerField()
    nombre = serializers.CharField()
    total_debe = serializers.DecimalField(max_digits=20, decimal_places=2)
    total_haber = serializers.DecimalField(max_digits=20, decimal_places=2)
    saldo = serializers.DecimalField(max_digits=20, decimal_places=2)
    net = serializers.DecimalField(max_digits=20, decimal_places=2)
    hijos = serializers.ListSerializer(child=serializers.DictField(), required=False)


class EstadoResultadosSerializer(serializers.Serializer):
    # Opción de lista plana de raíces (códigos 4 y 5) si se desea
    data = serializers.ListSerializer(child=EstadoResultadosCuentaSerializer(), required=False)
    # Opción con secciones "ingresos" y "costos_gastos"
    ingresos = serializers.ListSerializer(child=EstadoResultadosCuentaSerializer(), required=False)
    costos_gastos = serializers.ListSerializer(child=EstadoResultadosCuentaSerializer(), required=False)
    total_ingresos = serializers.DecimalField(max_digits=20, decimal_places=2, required=False)
    total_costos = serializers.DecimalField(max_digits=20, decimal_places=2, required=False)
    utilidad = serializers.DecimalField(max_digits=20, decimal_places=2, required=False)
