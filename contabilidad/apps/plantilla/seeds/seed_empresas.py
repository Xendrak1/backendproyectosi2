from ...empresa.models.empresa import Empresa
from ...empresa.models.user_empresa import UserEmpresa
from contabilidad.apps.empresa.models.custom import Custom
from contabilidad.apps.empresa.models.rol import RolEmpresa
from ...usuario.models.usuario import Persona, User
from ...gestion_cuenta.models.cuenta import Cuenta
from ...gestion_asiento.models.asiento_contable import AsientoContable
from ...gestion_asiento.models.movimiento import Movimiento
from decimal import Decimal
from datetime import datetime, timedelta
import random
from django.utils import timezone


def run():
    """Create a sample Empresa, a User and link them via UserEmpresa.

    Idempotent: uses get_or_create so it is safe to run multiple times.
    """

    # Datos de ejemplo
    empresa_data = {
        "nombre": "Empresa Demo S.A.",
        "nit": 123456789,
    }

    persona_data = {
        "nombre": "Ayrton",
        "apellido": "Desarrollador",
        "ci": "0000000",
        "telefono": "+59170000000",
    }

    username = "admin2"
    password = "123456"
    email = "admin2@gmail.com"
    # Crear o obtener Persona
    persona, _ = Persona.objects.get_or_create(
        nombre=persona_data["nombre"],
        apellido=persona_data["apellido"],
        defaults={
            "ci": persona_data["ci"],
            "telefono": persona_data["telefono"],
        },
    )

    # Crear o obtener usuario
    user, created_user = User.objects.get_or_create(
        username=username,
        defaults={
            "email": email,
            "persona": persona,
            "verified": True,
            "is_staff": True,
        },
    )
    if created_user:
        user.set_password(password)
        user.save()

    # Crear o obtener empresa
    empresa, _ = Empresa.objects.get_or_create(
        nombre=empresa_data["nombre"], defaults={"nit": empresa_data["nit"]}
    )

    custom, _ = Custom.objects.get_or_create(nombre="verde")

    rol, _ = RolEmpresa.objects.get_or_create(nombre="admin", empresa=empresa)



    # Vincular usuario y empresa en UserEmpresa
    ue, _ = UserEmpresa.objects.get_or_create(usuario=user, empresa=empresa, custom=custom)

    # Enlazar el rol con la relación intermedia UserEmpresa (no con User directo)
    rol.usuarios.add(ue)

    # --- IMPORTACIONES ADICIONALES REQUERIDAS (Asegúrate de tenerlas) ---
    # (Asumo que ya tienes 'random', 'timedelta', 'datetime', 'timezone', 'Decimal' 
    #  y tus modelos 'AsientoContable', 'Movimiento', 'Cuenta')
    # -----------------------------------------------------------------

    # --- (Tus importaciones de Django, modelos, random, datetime, Decimal, etc. van arriba) ---

    print(f"Seed empresas: usuario={user.username} (created={created_user}), empresa={empresa.nombre}, vinculo_id={ue.id if hasattr(ue, 'id') else 'n/a'}")
    print(f"--- 🚀 GENERANDO DATOS DEMO PARA: 'Importadora Andina S.R.L.' ---")

    # --- 1. BUSCAMOS TODAS LAS CUENTAS "UNIVERSALES" QUE USAREMOS ---
    # Para una demo, ¡las cargamos casi todas!
    try:
        cuentas = {
            # Activos
            "caja": Cuenta.objects.get(empresa=empresa, codigo="11102"),
            "banco": Cuenta.objects.get(empresa=empresa, codigo="11103"),
            "inv_temp": Cuenta.objects.get(empresa=empresa, codigo="11201"),
            "cli_nac": Cuenta.objects.get(empresa=empresa, codigo="11301"),
            "cli_ext": Cuenta.objects.get(empresa=empresa, codigo="11302"),
            "ant_prov": Cuenta.objects.get(empresa=empresa, codigo="11401"),
            "gastos_ant": Cuenta.objects.get(empresa=empresa, codigo="11501"),
            "cred_fiscal": Cuenta.objects.get(empresa=empresa, codigo="11601"), # (Aunque no lo usemos en asientos de 2 líneas, lo cargamos)
            "muebles": Cuenta.objects.get(empresa=empresa, codigo="12302"),
            "equipos": Cuenta.objects.get(empresa=empresa, codigo="12303"),
            "dep_acum": Cuenta.objects.get(empresa=empresa, codigo="12401"),

            # Pasivos
            "prestamo_cp": Cuenta.objects.get(empresa=empresa, codigo="21101"),
            "proveedores": Cuenta.objects.get(empresa=empresa, codigo="21201"),
            "cargas_sociales": Cuenta.objects.get(empresa=empresa, codigo="21301"),
            "deb_fiscal": Cuenta.objects.get(empresa=empresa, codigo="21401"), # (Ídem 'cred_fiscal')

            # Patrimonio
            "capital": Cuenta.objects.get(empresa=empresa, codigo="31101"),

            # Ingresos
            "ventas": Cuenta.objects.get(empresa=empresa, codigo="41101"),
            "ing_fin": Cuenta.objects.get(empresa=empresa, codigo="42101"),

            # Egresos
            "costo_ventas": Cuenta.objects.get(empresa=empresa, codigo="51101"), # ¡La cuenta clave!
            "sueldos": Cuenta.objects.get(empresa=empresa, codigo="52101"),
            "gasto_oficina": Cuenta.objects.get(empresa=empresa, codigo="52201"),
            "serv_prof": Cuenta.objects.get(empresa=empresa, codigo="52301"),
            "gasto_dep": Cuenta.objects.get(empresa=empresa, codigo="52401"),
            "impuestos": Cuenta.objects.get(empresa=empresa, codigo="52501"),
            "publicidad": Cuenta.objects.get(empresa=empresa, codigo="53101"),
            "gasto_ventas": Cuenta.objects.get(empresa=empresa, codigo="53201"),
            "gasto_financiero": Cuenta.objects.get(empresa=empresa, codigo="54101"),
            "otros_gastos": Cuenta.objects.get(empresa=empresa, codigo="55101"),
        }
    except Cuenta.DoesNotExist as e:
        print(f"❌ ERROR: No se encontró una cuenta DEMO esencial: {e}")
        print("Asegúrate de que todas las cuentas listadas en el diccionario 'cuentas' existan.")
        return

    print("✅ Todas las cuentas de 'Importadora Andina' cargadas.")
    asiento_creados = 0

    # --- 2. Plantillas de texto lógicas para "Importadora Andina S.R.L." ---
    plantillas_logicas = {
        # --- COMPRAS Y COSTOS (El corazón del negocio) ---
        'compra_mercaderia_credito': {
            "textos": ["Compra de 100 laptops HP s/factura 334", "Importación de 50 monitores Dell", "Pedido de 200 discos duros a proveedor", "Compra de mercadería al crédito"],
            "logica": [
                {"cuenta": cuentas["costo_ventas"], "debe": "monto", "haber": 0, "ref": "Compra de mercadería"}, # Simplificación: Gasto directo
                {"cuenta": cuentas["proveedores"], "debe": 0, "haber": "monto", "ref": "Crédito proveedor"}
            ]
        },
        'pago_proveedor': {
            "textos": ["Pago a proveedor 'Shenzhen Tech'", "Abono a factura 334", "Cancelación a proveedor de laptops", "Transferencia a proveedor"],
            "logica": [
                {"cuenta": cuentas["proveedores"], "debe": "monto", "haber": 0, "ref": "Pago a proveedor"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Salida de banco"}
            ]
        },
        'anticipo_proveedor': {
            "textos": ["Anticipo para importación de 500 tablets", "Pago inicial a proveedor 'Global Exports'", "Adelanto por pedido de hardware"],
            "logica": [
                {"cuenta": cuentas["ant_prov"], "debe": "monto", "haber": 0, "ref": "Anticipo a proveedor"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Pago anticipo"}
            ]
        },

        # --- VENTAS E INGRESOS ---
        'venta_credito_nacional': {
            "textos": ["Venta a 'TechCorp Bolivia' F/N-901", "Entrega de 10 laptops a 'Oficina SRL' a 30 días", "Factura de venta a cliente nacional"],
            "logica": [
                {"cuenta": cuentas["cli_nac"], "debe": "monto", "haber": 0, "ref": "Venta crédito F/901"},
                {"cuenta": cuentas["ventas"], "debe": 0, "haber": "monto", "ref": "Ingreso venta"}
            ]
        },
        'venta_credito_exterior': {
            "textos": ["Venta de 50 tablets a 'LimaTech' de Perú", "Exportación a cliente F/E-001", "Factura a cliente del exterior 'Bogota Systems'"],
            "logica": [
                {"cuenta": cuentas["cli_ext"], "debe": "monto", "haber": 0, "ref": "Venta exportación F/E-001"},
                {"cuenta": cuentas["ventas"], "debe": 0, "haber": "monto", "ref": "Ingreso venta"}
            ]
        },
        'cobro_cliente_nacional': {
            "textos": ["Cobro de factura F/N-901 de 'TechCorp'", "El cliente 'Oficina SRL' nos pagó", "Ingreso a banco de cliente nacional"],
            "logica": [
                {"cuenta": cuentas["banco"], "debe": "monto", "haber": 0, "ref": "Cobro F/N-901"},
                {"cuenta": cuentas["cli_nac"], "debe": 0, "haber": "monto", "ref": "Pago F/N-901"}
            ]
        },
        'venta_contado': {
            "textos": ["Venta de mostrador en efectivo", "Venta en efectivo de 1 mouse", "Ingreso por venta de contado"],
            "logica": [
                {"cuenta": cuentas["caja"], "debe": "monto", "haber": 0, "ref": "Ingreso por venta"},
                {"cuenta": cuentas["ventas"], "debe": 0, "haber": "monto", "ref": "Venta contado"}
            ]
        },

        # --- GASTOS OPERATIVOS ---
        'pago_sueldos': {
            "textos": ["Pago de sueldos del mes", "Planilla de salarios", "Adelanto de sueldo al gerente", "Liquidación de haberes del personal"],
            "logica": [
                {"cuenta": cuentas["sueldos"], "debe": "monto", "haber": 0, "ref": "Planilla de sueldos"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Pago planilla"}
            ]
        },
        'pago_cargas_sociales': {
            "textos": ["Pago de aportes a la AFP", "Cargas sociales del mes", "Pago a Caja de Salud"],
            "logica": [
                {"cuenta": cuentas["cargas_sociales"], "debe": "monto", "haber": 0, "ref": "Pago cargas sociales"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Pago banco"}
            ]
        },
        'gasto_publicidad': {
            "textos": ["Pago de publicidad en Facebook", "Anuncios de Google para laptops", "Campaña de marketing 'Cyber Monday'", "Factura de agencia de publicidad"],
            "logica": [
                {"cuenta": cuentas["publicidad"], "debe": "monto", "haber": 0, "ref": "Gasto publicidad"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Pago publicidad"}
            ]
        },
        'gasto_venta': {
            "textos": ["Comisión a vendedor por venta F/N-901", "Gastos de despacho de mercadería", "Stand en la feria 'ExpoTech'"],
            "logica": [
                {"cuenta": cuentas["gasto_ventas"], "debe": "monto", "haber": 0, "ref": "Gasto de venta"},
                {"cuenta": cuentas["caja"], "debe": 0, "haber": "monto", "ref": "Pago comisión"}
            ]
        },
        'gasto_oficina': {
            "textos": ["Compra de papelería", "Material de escritorio", "Recibo de agua potable", "Factura de internet de la oficina"],
            "logica": [
                {"cuenta": cuentas["gasto_oficina"], "debe": "monto", "haber": 0, "ref": "Gasto oficina"},
                {"cuenta": cuentas["caja"], "debe": 0, "haber": "monto", "ref": "Pago de caja"}
            ]
        },
        'gasto_profesional': {
            "textos": ["Pago a contador externo", "Honorarios de abogado por importación", "Servicios profesionales de auditoría", "Iguala del abogado"],
            "logica": [
                {"cuenta": cuentas["serv_prof"], "debe": "monto", "haber": 0, "ref": "Gasto profesional"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Pago honorarios"}
            ]
        },
        'pago_impuestos': {
            "textos": ["Pago de impuestos nacionales IVA F-200", "Pago del IT F-400", "Impuesto a las transacciones del mes"],
            "logica": [
                {"cuenta": cuentas["impuestos"], "debe": "monto", "haber": 0, "ref": "Pago impuestos"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Pago impuestos"}
            ]
        },
        'otros_gastos': {
            "textos": ["Gastos varios", "Reparación de aire acondicionado", "Gastos de taxi del mensajero", "Compra de café para la oficina"],
            "logica": [
                {"cuenta": cuentas["otros_gastos"], "debe": "monto", "haber": 0, "ref": "Gasto vario"},
                {"cuenta": cuentas["caja"], "debe": 0, "haber": "monto", "ref": "Salida de caja"}
            ]
        },

        # --- FINANZAS Y ACTIVOS ---
        'compra_equipos_contado': {
            "textos": ["Compra de 3 laptops para uso interno", "Nuevo servidor para la oficina", "Equipos de cómputo con cheque"],
            "logica": [
                {"cuenta": cuentas["equipos"], "debe": "monto", "haber": 0, "ref": "Compra activo"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Pago activo"}
            ]
        },
        'compra_muebles_credito': {
            "textos": ["Compra de escritorios al crédito", "Nuevas sillas para oficina F-45", "Muebles de 'Casa-Ideal' a 30 días"],
            "logica": [
                {"cuenta": cuentas["muebles"], "debe": "monto", "haber": 0, "ref": "Compra activo"},
                {"cuenta": cuentas["proveedores"], "debe": 0, "haber": "monto", "ref": "Cuenta por pagar"}
            ]
        },
        'recibir_prestamo': {
            "textos": ["Recepción de préstamo bancario", "Desembolso de crédito del banco", "Ingreso por préstamo a corto plazo"],
            "logica": [
                {"cuenta": cuentas["banco"], "debe": "monto", "haber": 0, "ref": "Ingreso préstamo"},
                {"cuenta": cuentas["prestamo_cp"], "debe": 0, "haber": "monto", "ref": "Registro pasivo"}
            ]
        },
        'gasto_banco': {
            "textos": ["Comisión bancaria por transferencia", "Mantenimiento de cuenta", "Gasto de la chequera", "Intereses de préstamo bancario"],
            "logica": [
                {"cuenta": cuentas["gasto_financiero"], "debe": "monto", "haber": 0, "ref": "Comisión banco"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Débito comisión"}
            ]
        },
        'compra_inversion_temp': {
            "textos": ["Compra de DPF a 90 días", "Inversión temporal en fondo mutuo", "Adquisición de bonos del banco"],
            "logica": [
                {"cuenta": cuentas["inv_temp"], "debe": "monto", "haber": 0, "ref": "Compra DPF"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Salida banco"}
            ]
        },
        'ingreso_financiero': {
            "textos": ["Intereses ganados por DPF", "Ingreso por inversión temporal", "Interés de fondo mutuo"],
            "logica": [
                {"cuenta": cuentas["banco"], "debe": "monto", "haber": 0, "ref": "Ingreso interés"},
                {"cuenta": cuentas["ing_fin"], "debe": 0, "haber": "monto", "ref": "Interés ganado"}
            ]
        },
        'pago_alquiler_anticipado': {
            "textos": ["Pago de 3 meses de alquiler por adelantado", "Alquiler pagado por anticipado", "Gasto de alquiler de oficina (anticipado)"],
            "logica": [
                {"cuenta": cuentas["gastos_ant"], "debe": "monto", "haber": 0, "ref": "Alquiler anticipado"},
                {"cuenta": cuentas["banco"], "debe": 0, "haber": "monto", "ref": "Pago alquiler"}
            ]
        },

        # --- APERTURA Y AJUSTES ---
        'gasto_depreciacion': {
            "textos": ["Depreciación del mes de equipos", "Ajuste por depreciación de muebles", "Asiento de depreciación de activos fijos"],
            "logica": [
                {"cuenta": cuentas["gasto_dep"], "debe": "monto", "haber": 0, "ref": "Gasto depreciación"},
                {"cuenta": cuentas["dep_acum"], "debe": 0, "haber": "monto", "ref": "Dep. acumulada"}
            ]
        },
        'apertura': {
            "textos": ["Asiento de apertura de 'Importadora Andina'", "Inicio de actividades", "Aporte de capital inicial"],
            "logica": [
                {"cuenta": cuentas["banco"], "debe": "monto", "haber": 0, "ref": "Aporte socio"},
                {"cuenta": cuentas["capital"], "debe": 0, "haber": "monto", "ref": "Capital social"}
            ]
        },
    }

    # --- 3. Bucle de Creación ---
    lista_tipos = list(plantillas_logicas.keys())
    asiento_creados = 0

    # (Aumentamos a 1000 para una mejor demo)
    for i in range(1000): 
        
        # 1. Elegir un tipo de asiento al azar
        tipo_asiento_key = random.choice(lista_tipos)
        plantilla = plantillas_logicas[tipo_asiento_key]
        
        # 2. Elegir una DESCRIPCIÓN de texto al azar
        descripcion_limpia = random.choice(plantilla["textos"])
        
        # 3. Definir el monto (con algo de lógica)
        monto_base = random.randint(100, 10000)
        if tipo_asiento_key in ['pago_sueldos', 'apertura', 'recibir_prestamo', 'compra_mercaderia_credito', 'venta_credito_exterior']:
            monto = Decimal(str(round(monto_base * 10 * random.uniform(0.8, 1.2), 2)))
        elif tipo_asiento_key in ['gasto_banco', 'otros_gastos', 'gasto_oficina']:
            monto = Decimal(str(round(monto_base / 10 * random.uniform(0.8, 1.2), 2)))
        else:
            monto = Decimal(str(round(monto_base * random.uniform(0.8, 1.2), 2)))
            
        if monto <= 0: monto = Decimal(str(random.randint(50, 150)))

        # 4. Crear el Asiento Contable (Encabezado)
        descripcion_unica = f"{descripcion_limpia} #{i+1}"
        
        asiento, created = AsientoContable.objects.get_or_create(
            empresa=empresa, 
            descripcion=descripcion_unica, 
            defaults={"estado": "APROBADO"}
        )

        if not created:
            continue 

        # 5. Asignar fecha histórica
        dias_atras = random.randint(1, 1095) # 1-3 años
        fecha = timezone.now().date() - timedelta(days=dias_atras)
        try:
            fecha_datetime = datetime.combine(fecha, datetime.min.time())
            fecha_aware = timezone.make_aware(fecha_datetime)
        except Exception:
            fecha_aware = timezone.now()
            fecha = fecha_aware.date()
            
        AsientoContable.objects.filter(pk=asiento.pk).update(created_at=fecha_aware, fecha=fecha)

        # 6. Crear los Movimientos (Detalle)
        for mov_plantilla in plantilla["logica"]:
            Movimiento.objects.create(
                referencia=mov_plantilla["ref"],
                debe=monto if mov_plantilla["debe"] == "monto" else Decimal("0"),
                haber=monto if mov_plantilla["haber"] == "monto" else Decimal("0"),
                cuenta=mov_plantilla["cuenta"],
                asiento_contable=asiento,
            )

        asiento_creados += 1

    print(f"✅ Se crearon {asiento_creados} asientos DEMO para 'Importadora Andina' usando casi todas las cuentas.")