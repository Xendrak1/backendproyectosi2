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
            ClaseCuenta.objects.filter(empresa=empresa, padre=None, codigo__in=[1, 2, 3])
            .prefetch_related("hijos", "cuentas")
)

        # Función recursiva para calcular saldos
        def calcular_saldo(clase):
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

                total_debe_c = mov_c["total_debe"] or 0
                total_haber_c = mov_c["total_haber"] or 0
                saldo_c = total_debe_c - total_haber_c

                cuentas_data.append({
                    "codigo": getattr(cuenta, "codigo", None),
                    "nombre": getattr(cuenta, "nombre", ""),
                    "total_debe": total_debe_c,
                    "total_haber": total_haber_c,
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
            movimientos = Movimiento.objects.filter(
                cuenta_id__in=ids_cuenta,
                asiento_contable__created_at__gte=fecha_inicio_dt,
                asiento_contable__created_at__lt=fecha_fin_dt,
            ).aggregate(total_debe=Sum("debe"), total_haber=Sum("haber"))

            total_debe = movimientos["total_debe"] or 0
            total_haber = movimientos["total_haber"] or 0
            saldo = total_debe - total_haber

            # Combinar: primero mostrar cuentas directas como hojas, luego las subclases
            hijos_completos = cuentas_data + hijos_data

            return {
                "codigo": clase.codigo,
                "nombre": clase.nombre,
                "total_debe": total_debe,
                "total_haber": total_haber,
                "saldo": saldo,
                "hijos": hijos_completos,
                "ids": ids_cuenta,  # opcional, puedes eliminar si no necesitas
            }

        resultado = [calcular_saldo(clase) for clase in clases.filter(padre=None)]

        return Response(resultado)

    @action(detail=False, methods=["get"], url_path="export/pdf")
    def export_pdf(self, request):
        # Parámetros de fecha
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
            ids_cuenta = [cuenta.id for cuenta in clase.cuentas.all()]
            cuentas_data = []
            for cuenta in clase.cuentas.all():
                mov_c = Movimiento.objects.filter(
                    cuenta_id=cuenta.id,
                    asiento_contable__created_at__gte=fecha_inicio_dt,
                    asiento_contable__created_at__lt=fecha_fin_dt,
                ).aggregate(total_debe=Sum("debe"), total_haber=Sum("haber"))
                total_debe_c = mov_c["total_debe"] or 0
                total_haber_c = mov_c["total_haber"] or 0
                saldo_c = total_debe_c - total_haber_c
                cuentas_data.append({
                    "codigo": getattr(cuenta, "codigo", None),
                    "nombre": getattr(cuenta, "nombre", ""),
                    "total_debe": total_debe_c,
                    "total_haber": total_haber_c,
                    "saldo": saldo_c,
                    "hijos": [],
                    "ids": [cuenta.id],
                })

            hijos_data = []
            for hijo in clase.hijos.all():
                hijo_data = calcular_saldo(hijo)
                hijos_data.append(hijo_data)
                ids_cuenta.extend(hijo_data.get("ids", []))

            movimientos = Movimiento.objects.filter(
                cuenta_id__in=ids_cuenta,
                asiento_contable__created_at__gte=fecha_inicio_dt,
                asiento_contable__created_at__lt=fecha_fin_dt,
            ).aggregate(total_debe=Sum("debe"), total_haber=Sum("haber"))

            total_debe = movimientos["total_debe"] or 0
            total_haber = movimientos["total_haber"] or 0
            saldo = total_debe - total_haber

            hijos_completos = cuentas_data + hijos_data

            return {
                "codigo": clase.codigo,
                "nombre": clase.nombre,
                "total_debe": total_debe,
                "total_haber": total_haber,
                "saldo": saldo,
                "hijos": hijos_completos,
                "ids": ids_cuenta,
            }

        data = [calcular_saldo(c) for c in clases.filter(padre=None)]
        # Totales a nivel raíz para no doble contar
        total_debe = sum((n.get("total_debe") or 0) for n in data)
        total_haber = sum((n.get("total_haber") or 0) for n in data)
        totales = {
            "debe": total_debe,
            "haber": total_haber,
            "saldo": total_debe - total_haber,
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