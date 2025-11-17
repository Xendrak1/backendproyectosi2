# apps/libro/views.py
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum
from ...gestion_cuenta.models import ClaseCuenta, Cuenta
from ...gestion_asiento.models import Movimiento
from datetime import datetime, timedelta
from ..services.pdf import render_to_pdf, build_pdf_response

class BalanceGeneralViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    pagination_class = None  # desactiva paginación
    
    NATURALEZA = {
        1: 1,   # Activo → naturaleza DEUDORA
        2: -1,  # Pasivo → naturaleza ACREEDORA
        3: -1,  # Patrimonio → naturaleza ACREEDORA
        4: -1,
        5: 1,
    }

    def list(self, request):
        fecha_inicio = request.query_params.get("fecha_inicio", "2010-01-01")
        fecha_fin = request.query_params.get("fecha_fin", datetime.now().strftime("%Y-%m-%d"))

        try:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=400)

        empresa = request.auth.get('empresa')
        if not empresa:
            return Response({"error": "Usuario sin empresa asignada"}, status=400)

        # 1. OPTIMIZACIÓN: Traer todas las cuentas de la empresa UNA SOLA VEZ
        # Asumiendo que tu modelo Cuenta está en gestion_cuenta
        cuentas_empresa_ids = Cuenta.objects.filter(
            clase_cuenta__empresa=empresa
        ).values_list("id", flat=True)

        # 2. OPTIMIZACIÓN: Traer TODOS los movimientos en UNA SOLA CONSULTA
        movimientos_agrupados = Movimiento.objects.filter(
            cuenta_id__in=cuentas_empresa_ids,
            asiento_contable__created_at__gte=fecha_inicio_dt,
            asiento_contable__created_at__lt=fecha_fin_dt,
        ).values("cuenta_id").annotate(
            total_debe=Sum("debe"),
            total_haber=Sum("haber")
        )

        # 3. OPTIMIZACIÓN: Convertir los movimientos en un diccionario para acceso rápido
        # Esto nos da: { cuenta_id_1: {"debe": X, "haber": Y}, ... }
        saldos_por_cuenta = {
            m["cuenta_id"]: {"debe": m["total_debe"] or 0, "haber": m["total_haber"] or 0}
            for m in movimientos_agrupados
        }

        # Traer todas las clases raíz (1-5) y sus descendientes
        clases_raiz = (
            ClaseCuenta.objects.filter(empresa=empresa, padre=None, codigo__in=[1, 2, 3, 4, 5])
            .prefetch_related("hijos", "cuentas") # prefetch_related ayuda a la recursión
        )

        # 4. FUNCIÓN RECURSIVA OPTIMIZADA
        # Esta función YA NO HACE CONSULTAS A LA DB, solo usa el diccionario "saldos_por_cuenta"
        def calcular_saldo_optimizado(clase, saldos_map):
            # Asegúrate que self.NATURALEZA (a nivel de clase) esté completo (1-5)
            naturaleza = self.NATURALEZA.get(clase.codigo, 1)
            
            total_debe_clase = 0
            total_haber_clase = 0
            cuentas_data = []
            
            # Sumar cuentas "hoja" de esta clase
            for cuenta in clase.cuentas.all():
                saldos = saldos_map.get(cuenta.id, {"debe": 0, "haber": 0})
                debe = saldos["debe"]
                haber = saldos["haber"]
                
                total_debe_clase += debe
                total_haber_clase += haber

                # Solo agregar si tiene saldo
                if debe != 0 or haber != 0:
                    cuentas_data.append({
                        "codigo": getattr(cuenta, "codigo", None),
                        "nombre": getattr(cuenta, "nombre", ""),
                        "total_debe": debe,
                        "total_haber": haber,
                        "saldo": (debe - haber) * naturaleza,
                        "hijos": [],
                    })

            # Recursivamente sumar hijos (clases)
            hijos_data = []
            for hijo in clase.hijos.all():
                hijo_data = calcular_saldo_optimizado(hijo, saldos_map)
                
                # Acumular totales del hijo
                total_debe_clase += hijo_data["total_debe"]
                total_haber_clase += hijo_data["total_haber"]
                
                # Solo agregar si el hijo tiene saldo
                if hijo_data["total_debe"] != 0 or hijo_data["total_haber"] != 0:
                    hijos_data.append(hijo_data)

            # Calcular saldo total para esta clase (incluye cuentas propias + hijos)
            saldo_total = (total_debe_clase - total_haber_clase) * naturaleza

            return {
                "codigo": clase.codigo,
                "nombre": clase.nombre,
                "total_debe": total_debe_clase,
                "total_haber": total_haber_clase,
                "saldo": saldo_total,
                "hijos": cuentas_data + hijos_data,
            }

        # --- Lógica principal (como la teníamos) ---
        total_ingresos = 0
        total_gastos = 0
        resultado_final_nodos = [] # Lista solo para nodos 1, 2, 3
        nodo_patrimonio = None

        for clase in clases_raiz:
            # Usamos la nueva función optimizada
            nodo_calculado = calcular_saldo_optimizado(clase, saldos_por_cuenta)
            
            codigo = clase.codigo
            if codigo == 4: # Ingreso
                total_ingresos = nodo_calculado["saldo"]
            elif codigo == 5: # Gasto
                total_gastos = nodo_calculado["saldo"]
            else: # Activo (1), Pasivo (2), Patrimonio (3)
                resultado_final_nodos.append(nodo_calculado)
                if codigo == 3:
                    nodo_patrimonio = nodo_calculado

        # Calcular resultado del ejercicio (Ej: 15000 - 9800 = 5200)
        resultado_ejercicio = total_ingresos - total_gastos
        
        # Sumar al patrimonio (si existe)
        if nodo_patrimonio:
            # Ej: 50000 (saldo original) + 5200 (resultado ej.)
            nodo_patrimonio["saldo"] += resultado_ejercicio

        # Devolver solo Activo, Pasivo y Patrimonio (ya modificados)
        return Response(resultado_final_nodos)

    @action(detail=False, methods=["get"], url_path="export/pdf")
    def export_pdf(self, request):
        fecha_inicio = request.query_params.get("fecha_inicio", "2010-01-01")
        fecha_fin = request.query_params.get("fecha_fin", datetime.now().strftime("%Y-%m-%d"))

        try:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=400)

        empresa = request.auth.get('empresa')
        if not empresa:
            return Response({"error": "Usuario sin empresa asignada"}, status=400)

        # 1. OPTIMIZACIÓN: Traer IDs de todas las cuentas de la empresa
        cuentas_empresa_ids = Cuenta.objects.filter(
            clase_cuenta__empresa=empresa
        ).values_list("id", flat=True)

        # 2. OPTIMIZACIÓN: Traer movimientos agrupados (1 sola consulta)
        movimientos_agrupados = Movimiento.objects.filter(
            cuenta_id__in=cuentas_empresa_ids,
            asiento_contable__created_at__gte=fecha_inicio_dt,
            asiento_contable__created_at__lt=fecha_fin_dt,
        ).values("cuenta_id").annotate(
            total_debe=Sum("debe"),
            total_haber=Sum("haber")
        )

        # Diccionario rápido para buscar saldos
        saldos_por_cuenta = {
            m["cuenta_id"]: {"debe": m["total_debe"] or 0, "haber": m["total_haber"] or 0}
            for m in movimientos_agrupados
        }

        # 3. Traer clases raíz (1 a 5) para calcular todo el ejercicio
        clases_raiz = (
            ClaseCuenta.objects.filter(empresa=empresa, padre=None, codigo__in=[1, 2, 3, 4, 5])
            .prefetch_related("hijos", "cuentas")
        )

        # Función recursiva optimizada (sin queries)
        def calcular_saldo_optimizado(clase, saldos_map):
            naturaleza = self.NATURALEZA.get(clase.codigo, 1)
            total_debe_clase = 0
            total_haber_clase = 0
            cuentas_data = []

            for cuenta in clase.cuentas.all():
                saldos = saldos_map.get(cuenta.id, {"debe": 0, "haber": 0})
                debe = saldos["debe"]
                haber = saldos["haber"]
                total_debe_clase += debe
                total_haber_clase += haber

                # Incluimos cuentas aunque estén en cero si se prefiere, o filtramos
                if debe != 0 or haber != 0:
                    cuentas_data.append({
                        "codigo": getattr(cuenta, "codigo", None),
                        "nombre": getattr(cuenta, "nombre", ""),
                        "total_debe": debe,
                        "total_haber": haber,
                        "saldo": (debe - haber) * naturaleza,
                        "hijos": [],
                    })

            hijos_data = []
            for hijo in clase.hijos.all():
                hijo_data = calcular_saldo_optimizado(hijo, saldos_map)
                total_debe_clase += hijo_data["total_debe"]
                total_haber_clase += hijo_data["total_haber"]
                # Mostrar hijos si tienen saldo
                if hijo_data["total_debe"] != 0 or hijo_data["total_haber"] != 0:
                    hijos_data.append(hijo_data)

            saldo_total = (total_debe_clase - total_haber_clase) * naturaleza

            return {
                "codigo": clase.codigo,
                "nombre": clase.nombre,
                "total_debe": total_debe_clase,
                "total_haber": total_haber_clase,
                "saldo": saldo_total,
                "hijos": cuentas_data + hijos_data,
                "ids": [], # No lo necesitamos en el PDF
            }

        # 4. Calcular lógica de negocio
        total_ingresos = 0
        total_gastos = 0
        data_balance = [] # Lista final solo con 1, 2 y 3
        nodo_patrimonio = None

        for clase in clases_raiz:
            nodo = calcular_saldo_optimizado(clase, saldos_por_cuenta)
            
            if clase.codigo == 4: # Ingresos
                total_ingresos = nodo["saldo"]
            elif clase.codigo == 5: # Gastos
                total_gastos = nodo["saldo"]
            elif clase.codigo in [1, 2, 3]: # Activo, Pasivo, Patrimonio
                data_balance.append(nodo)
                if clase.codigo == 3:
                    nodo_patrimonio = nodo

        # 5. Aplicar resultado del ejercicio al Patrimonio
        resultado_ejercicio = total_ingresos - total_gastos
        if nodo_patrimonio:
            nodo_patrimonio["saldo"] += resultado_ejercicio

        # 6. Calcular totales finales para el template
        totales = {
            "debe": sum(i["total_debe"] for i in data_balance),
            "haber": sum(i["total_haber"] for i in data_balance),
            "saldo": sum(i["saldo"] for i in data_balance),
        }

        context = {
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "data": data_balance,
            "totales": totales,
        }

        pdf = render_to_pdf("reporte/balance_general_pdf.html", context)
        filename = f"balance_general_{fecha_fin}.pdf"
        return build_pdf_response(pdf, filename)