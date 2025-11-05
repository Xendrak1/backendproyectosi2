from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum
from datetime import datetime, timedelta

from ...gestion_cuenta.models import ClaseCuenta
from ...gestion_asiento.models import Movimiento
from ..services.pdf import render_to_pdf, build_pdf_response


class EstadoResultadosViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    pagination_class = None

    def list(self, request):
        # Parámetros de fecha
        fecha_inicio = request.query_params.get("fecha_inicio", "2010-01-01")
        fecha_fin = request.query_params.get("fecha_fin", datetime.now().strftime("%Y-%m-%d"))

        try:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=400)

        # Empresa del usuario
        empresa = request.auth.get('empresa') if hasattr(request, 'auth') and request.auth else None
        if not empresa:
            return Response({"error": "Usuario sin empresa asignada"}, status=400)

        # Traer clases raíz 4 (INGRESOS) y 5 (COSTOS Y GASTOS)
        clases = (
            ClaseCuenta.objects.filter(empresa=empresa, padre=None, codigo__in=[4, 5])
            .prefetch_related("hijos", "cuentas")
        )

        def calcular(clase):
            # IDs de cuentas asociadas a esta clase
            ids_cuenta = [c.id for c in clase.cuentas.all()]

            # Recursivamente procesar subclases
            hijos_data = []
            for hijo in clase.hijos.all():
                hijo_data = calcular(hijo)
                hijos_data.append(hijo_data)
                ids_cuenta.extend(hijo_data.get("ids", []))

            # Agregar movimientos de todas las cuentas de esta clase y descendientes
            movimientos = (
                Movimiento.objects.filter(
                    cuenta_id__in=ids_cuenta,
                    asiento_contable__created_at__gte=fecha_inicio_dt,
                    asiento_contable__created_at__lt=fecha_fin_dt,
                )
                .aggregate(total_debe=Sum("debe"), total_haber=Sum("haber"))
            )

            total_debe = movimientos["total_debe"] or 0
            total_haber = movimientos["total_haber"] or 0
            saldo = total_debe - total_haber

            # Para estado de resultados: ingresos (4) net = haber - debe, costos/gastos (5) net = debe - haber
            if str(clase.codigo).startswith("4"):
                net = total_haber - total_debe
            else:
                net = total_debe - total_haber

            return {
                "codigo": clase.codigo,
                "nombre": clase.nombre,
                "total_debe": total_debe,
                "total_haber": total_haber,
                "saldo": saldo,
                "net": net,
                "hijos": hijos_data,
                "ids": ids_cuenta,
            }

        resultado = [calcular(clase) for clase in clases.filter(padre=None)]

        # También devolver totales de ingresos (4) y costos/gastos (5)
        total_ingresos = sum(r.get("net", 0) for r in resultado if str(r.get("codigo", "")).startswith("4"))
        total_costos = sum(r.get("net", 0) for r in resultado if str(r.get("codigo", "")).startswith("5"))
        utilidad = total_ingresos - total_costos

        return Response({
            "data": resultado,
            "total_ingresos": total_ingresos,
            "total_costos": total_costos,
            "utilidad": utilidad,
        })

    @action(detail=False, methods=["get"], url_path="export/pdf")
    def export_pdf(self, request):
        fecha_inicio = request.query_params.get("fecha_inicio", "2010-01-01")
        fecha_fin = request.query_params.get("fecha_fin", datetime.now().strftime("%Y-%m-%d"))

        try:
            fecha_inicio_dt = datetime.strptime(fecha_inicio, "%Y-%m-%d")
            fecha_fin_dt = datetime.strptime(fecha_fin, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            return Response({"error": "Formato de fecha inválido. Use YYYY-MM-DD"}, status=400)

        empresa = request.auth.get('empresa') if hasattr(request, 'auth') and request.auth else None
        if not empresa:
            return Response({"error": "Usuario sin empresa asignada"}, status=400)

        clases = (
            ClaseCuenta.objects.filter(empresa=empresa, padre=None, codigo__in=[4, 5])
            .prefetch_related("hijos", "cuentas")
        )

        def calcular(clase):
            ids_cuenta = [c.id for c in clase.cuentas.all()]
            hijos_data = []
            for hijo in clase.hijos.all():
                hijo_data = calcular(hijo)
                hijos_data.append(hijo_data)
                ids_cuenta.extend(hijo_data.get("ids", []))
            movimientos = (
                Movimiento.objects.filter(
                    cuenta_id__in=ids_cuenta,
                    asiento_contable__created_at__gte=fecha_inicio_dt,
                    asiento_contable__created_at__lt=fecha_fin_dt,
                )
                .aggregate(total_debe=Sum("debe"), total_haber=Sum("haber"))
            )
            total_debe = movimientos["total_debe"] or 0
            total_haber = movimientos["total_haber"] or 0
            saldo = total_debe - total_haber
            if str(clase.codigo).startswith("4"):
                net = total_haber - total_debe
            else:
                net = total_debe - total_haber
            return {
                "codigo": clase.codigo,
                "nombre": clase.nombre,
                "total_debe": total_debe,
                "total_haber": total_haber,
                "saldo": saldo,
                "net": net,
                "hijos": hijos_data,
                "ids": ids_cuenta,
            }

        data = [calcular(c) for c in clases.filter(padre=None)]
        total_ingresos = sum(r.get("net", 0) for r in data if str(r.get("codigo", "")).startswith("4"))
        total_costos = sum(r.get("net", 0) for r in data if str(r.get("codigo", "")).startswith("5"))
        utilidad = total_ingresos - total_costos

        context = {
            "fecha_inicio": fecha_inicio,
            "fecha_fin": fecha_fin,
            "data": data,
            "total_ingresos": total_ingresos,
            "total_costos": total_costos,
            "utilidad": utilidad,
        }

        pdf = render_to_pdf("reporte/estado_resultados_pdf.html", context)
        filename = f"estado_resultados_{fecha_fin}.pdf"
        return build_pdf_response(pdf, filename)