from ...suscripcion.models import Estado, Plan, Caracteristica, TipoPlan

def run():
    # Cargar estados
    estados = [
        {"nombre": "pendiente"},
        {"nombre": "activo"},
        {"nombre": "nulo"},
    ]
    for e in estados:
        Estado.objects.get_or_create(nombre=e["nombre"])

    # Cargar planes
    plan_basic, _ = Plan.objects.get_or_create(
        codigo="BASIC",
        defaults={"nombre": "Básico", "descripcion": "Plan inicial"}
    )
    plan_pro, _ = Plan.objects.get_or_create(
        codigo="PREMIUM",
        defaults={"nombre": "Profesional", "descripcion": "Plan avanzado"}
    )
    plan_emp, _ = Plan.objects.get_or_create(
        codigo="BUSINESS",
        defaults={"nombre": "Empresarial", "descripcion": "Plan para empresas"}
    )

    #  Cargar características
    car_basic, _ = Caracteristica.objects.get_or_create(
        codigo="CAR_BASIC",
        defaults={"cant_empresas": 1, "cant_colab": 1, "funcionalidad": "basicas", "cant_consultas_ia": None}
    )
    car_pro, _ = Caracteristica.objects.get_or_create(
        codigo="CAR_PREMIUM",
        defaults={"cant_empresas": 5, "cant_colab": 10, "funcionalidad": "generales, acceso a IA", "cant_consultas_ia": 3}
    )
    car_emp, _ = Caracteristica.objects.get_or_create(
        codigo="CAR_BUSINESS",
        defaults={"cant_empresas": None, "cant_colab": None, "funcionalidad": "completa, acceso a IA", "cant_consultas_ia": 10}
    )

    # Cargar tipos de plan usando objetos
    tipos_de_plan = [
        {"duracion_mes": 1, "precio": 0.0, "codigo": "gr00", "plan": plan_basic, "caracteristica": car_basic},
        {"duracion_mes": 1, "precio": 0.1, "codigo": "pro06", "plan": plan_pro, "caracteristica": car_pro},
        {"duracion_mes": 12, "precio": 0.1, "codigo": "pro12", "plan": plan_pro, "caracteristica": car_pro},
        {"duracion_mes": 1, "precio": 0.1, "codigo": "emp06", "plan": plan_emp, "caracteristica": car_emp},
        {"duracion_mes": 12, "precio": 0.1, "codigo": "emp12", "plan": plan_emp, "caracteristica": car_emp},
    ]

    for t in tipos_de_plan:
        TipoPlan.objects.get_or_create(
            codigo=t["codigo"],
            defaults={
                "duracion_mes": t["duracion_mes"],
                "precio": t["precio"],
                "plan": t["plan"],
                "caracteristica": t["caracteristica"]
            }
        )

    print("Seeds iniciales de suscripcion cargados correctamente")

