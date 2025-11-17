from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum
from datetime import datetime, timedelta

# --- IMPORTACIONES CLAVE (Asegúrate de tener esto así) ---
from ...gestion_cuenta.models import ClaseCuenta, Cuenta
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

        empresa = request.auth.get('empresa') if hasattr(request, 'auth') and request.auth else None
        if not empresa:
            return Response({"error": "Usuario sin empresa asignada"}, status=400)

        # --- OPTIMIZACIÓN LIST ---
        cuentas_empresa_ids = Cuenta.objects.filter(
            clase_cuenta__empresa=empresa
        ).values_list("id", flat=True)

        movimientos_agrupados = Movimiento.objects.filter(
            cuenta_id__in=cuentas_empresa_ids,
            asiento_contable__created_at__gte=fecha_inicio_dt,
            asiento_contable__created_at__lt=fecha_fin_dt,
        ).values("cuenta_id").annotate(
            total_debe=Sum("debe"),
            total_haber=Sum("haber")
        )

        saldos_por_cuenta = {
            m["cuenta_id"]: {"debe": m["total_debe"] or 0, "haber": m["total_haber"] or 0}
            for m in movimientos_agrupados
        }

        clases = (
            ClaseCuenta.objects.filter(empresa=empresa, padre=None, codigo__in=[4, 5])
            .prefetch_related("hijos", "cuentas")
        )

        def calcular_optimizado(clase, saldos_map):
            total_debe = 0
            total_haber = 0
            
            # Sumar cuentas propias (hojas)
            for cuenta in clase.cuentas.all():
                saldos = saldos_map.get(cuenta.id, {"debe": 0, "haber": 0})
                total_debe += saldos["debe"]
                total_haber += saldos["haber"]

            hijos_data = []
            for hijo in clase.hijos.all():
                hijo_data = calcular_optimizado(hijo, saldos_map)
                total_debe += hijo_data["total_debe"]
                total_haber += hijo_data["total_haber"]
                hijos_data.append(hijo_data)

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
                "ids": [], # Ya no se usa
            }

        resultado = [calcular_optimizado(c, saldos_por_cuenta) for c in clases]

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

        # --- OPTIMIZACIÓN PDF ---
        cuentas_empresa_ids = Cuenta.objects.filter(
            clase_cuenta__empresa=empresa
        ).values_list("id", flat=True)

        movimientos_agrupados = Movimiento.objects.filter(
            cuenta_id__in=cuentas_empresa_ids,
            asiento_contable__created_at__gte=fecha_inicio_dt,
            asiento_contable__created_at__lt=fecha_fin_dt,
        ).values("cuenta_id").annotate(
            total_debe=Sum("debe"),
            total_haber=Sum("haber")
        )

        saldos_por_cuenta = {
            m["cuenta_id"]: {"debe": m["total_debe"] or 0, "haber": m["total_haber"] or 0}
            for m in movimientos_agrupados
        }

        clases = (
            ClaseCuenta.objects.filter(empresa=empresa, padre=None, codigo__in=[4, 5])
            .prefetch_related("hijos", "cuentas")
        )

        def calcular_optimizado(clase, saldos_map):
            total_debe = 0
            total_haber = 0
            
            for cuenta in clase.cuentas.all():
                saldos = saldos_map.get(cuenta.id, {"debe": 0, "haber": 0})
                total_debe += saldos["debe"]
                total_haber += saldos["haber"]

            hijos_data = []
            for hijo in clase.hijos.all():
                hijo_data = calcular_optimizado(hijo, saldos_map)
                total_debe += hijo_data["total_debe"]
                total_haber += hijo_data["total_haber"]
                hijos_data.append(hijo_data)

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
                "ids": [],
            }

        data = [calcular_optimizado(c, saldos_por_cuenta) for c in clases]

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