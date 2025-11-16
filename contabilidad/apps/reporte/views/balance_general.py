# apps/libro/views.py
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum
from ...gestion_cuenta.models import ClaseCuenta
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
        # Parámetros de fecha
        fecha_inicio = request.query_params.get("fecha_inicio", "2010-01-01")
        fecha_fin = request.query_params.get("fecha_fin", datetime.now().strftime("%Y-%m-%d"))

        try:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d") + timedelta(days=1)  # incluye todo el día
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=400)

        # Empresa del usuario (ajustar según tu modelo)
        request = self.request
        empresa = request.auth.get('empresa')
        if not empresa:
            return Response({"error": "Usuario sin empresa asignada"}, status=400)

        # Traer todas las clases de la empresa y prefetch cuentas e hijos
        clases = (
            ClaseCuenta.objects.filter(empresa=empresa, padre=None, codigo__in=[1, 2, 3, 4, 5])
            .prefetch_related("hijos", "cuentas")
)

        # Función recursiva para calcular saldos
        def calcular_saldo(clase):
            naturaleza = self.NATURALEZA.get(clase.codigo, 1)
            # IDs de cuentas propias
            ids_cuenta = [cuenta.id for cuenta in clase.cuentas.all()]

            # Construir nodos por cuenta (hojas) para que el frontend pueda mostrar cuentas como 1111
            cuentas_data = []
            for cuenta in clase.cuentas.all():
                mov_c = Movimiento.objects.filter(
                    cuenta_id=cuenta.id,
                    asiento_contable__created_at__gte=fecha_inicio_dt,
                    asiento_contable__created_at__lt=fecha_fin_dt,
                ).aggregate(total_debe=Sum("debe"), total_haber=Sum("haber"))

                debe = mov_c["total_debe"] or 0
                haber = mov_c["total_haber"] or 0
                saldo_c = (debe - haber) * naturaleza

                cuentas_data.append({
                    "codigo": getattr(cuenta, "codigo", None),
                    "nombre": getattr(cuenta, "nombre", ""),
                    "total_debe": debe,
                    "total_haber": haber,
                    "saldo": saldo_c,
                    "hijos": [],
                    "ids": [cuenta.id],
                })

            # Recursivamente sumar hijos (clases)
            hijos_data = []
            for hijo in clase.hijos.all():
                hijo_data = calcular_saldo(hijo)
                hijos_data.append(hijo_data)
                ids_cuenta.extend(hijo_data.get("ids", []))

            # Movimientos de esas cuentas (incluye cuentas propias + hijos)
            mov_total = Movimiento.objects.filter(
                cuenta_id__in=ids_cuenta,
                asiento_contable__created_at__gte=fecha_inicio_dt,
                asiento_contable__created_at__lt=fecha_fin_dt,
            ).aggregate(total_debe=Sum("debe"), total_haber=Sum("haber"))

            total_debe = mov_total.get("total_debe") or 0
            total_haber = mov_total.get("total_haber") or 0
            saldo_total = (total_debe - total_haber) * naturaleza

            # Combinar: primero mostrar cuentas directas como hojas, luego las subclases
            #hijos_completos = cuentas_data + hijos_data

            return {
                "codigo": clase.codigo,
                "nombre": clase.nombre,
                "total_debe": total_debe,
                "total_haber": total_haber,
                "saldo": saldo_total,
                "hijos": cuentas_data + hijos_data,
                "ids": ids_cuenta,  # opcional, puedes eliminar si no necesitas
            }

        resultado = [calcular_saldo(c) for c in clases]

        total_ingresos = 0
        total_gastos = 0
        resultado_final_nodo = []
        nodo_patrimonio = None

        # Buscar los nodos de ingresos (4) y gastos (5) en todas las clases cargadas
        for clase in clases:
            nodo_calculado = calcular_saldo(clase)
            codigo = clase.codigo
            if codigo == 4: # Ingreso
                total_ingresos = nodo_calculado["saldo"]
            elif codigo == 5: # Gasto
                total_gastos = nodo_calculado["saldo"]
            else: # Activo (1), Pasivo (2), Patrimonio (3)
                resultado_final_nodo.append(nodo_calculado)
                # Guardamos la referencia al nodo de patrimonio
                if codigo == 3:
                    nodo_patrimonio = nodo_calculado

        resultado_ejercicio = total_ingresos - total_gastos
        
        if nodo_patrimonio:
            nodo_patrimonio["saldo"] += resultado_ejercicio

        return Response(resultado)

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

        clases = (
            ClaseCuenta.objects.filter(empresa=empresa, padre=None, codigo__in=[1, 2, 3])
            .prefetch_related("hijos", "cuentas")
        )

        def calcular_saldo(clase):
            naturaleza = self.NATURALEZA.get(clase.codigo, 1)
            cuentas_ids = [c.id for c in clase.cuentas.all()]
            cuentas_data = []

            for cuenta in clase.cuentas.all():
                mov = Movimiento.objects.filter(
                    cuenta_id=cuenta.id,
                    asiento_contable__created_at__gte=fecha_inicio_dt,
                    asiento_contable__created_at__lt=fecha_fin_dt,
                ).aggregate(total_debe=Sum("debe"), total_haber=Sum("haber"))

                debe = mov.get("total_debe") or 0
                haber = mov.get("total_haber") or 0
                saldo = (debe - haber) * naturaleza

                cuentas_data.append({
                    "codigo": cuenta.codigo,
                    "nombre": cuenta.nombre,
                    "total_debe": debe,
                    "total_haber": haber,
                    "saldo": saldo,
                    "hijos": [],
                    "ids": [cuenta.id],
                })

            hijos_data = []
            for hijo in clase.hijos.all():
                hijo_data = calcular_saldo(hijo)
                hijos_data.append(hijo_data)
                cuentas_ids.extend(hijo_data["ids"])

            mov_total = Movimiento.objects.filter(
                cuenta_id__in=cuentas_ids,
                asiento_contable__created_at__gte=fecha_inicio_dt,
                asiento_contable__created_at__lt=fecha_fin_dt,
            ).aggregate(total_debe=Sum("debe"), total_haber=Sum("haber"))

            total_debe = mov_total.get("total_debe") or 0
            total_haber = mov_total.get("total_haber") or 0
            saldo_total = (total_debe - total_haber) * naturaleza

            return {
                "codigo": clase.codigo,
                "nombre": clase.nombre,
                "total_debe": total_debe,
                "total_haber": total_haber,
                "saldo": saldo_total,
                "hijos": cuentas_data + hijos_data,
                "ids": cuentas_ids,
            }

        data = [calcular_saldo(c) for c in clases]

        totales = {
            "debe": sum(i["total_debe"] for i in data),
            "haber": sum(i["total_haber"] for i in data),
            "saldo": sum(i["saldo"] for i in data),
        }

        context = {
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "data": data,
            "totales": totales,
        }

        pdf = render_to_pdf("reporte/balance_general_pdf.html", context)
        filename = f"balance_general_{fecha_fin}.pdf"
        return build_pdf_response(pdf, filename)