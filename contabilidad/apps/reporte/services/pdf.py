from io import BytesIO
from django.http import HttpResponse
from django.template import loader

try:
    # Prefer xhtml2pdf for portability
    from xhtml2pdf import pisa
except ImportError:  # pragma: no cover
    pisa = None


def render_to_pdf(template_name: str, context: dict) -> bytes:
    """Render a Django template to PDF bytes using xhtml2pdf.

    Raises RuntimeError if xhtml2pdf is not installed.
    """
    if pisa is None:
        raise RuntimeError("xhtml2pdf no está instalado. Agrega 'xhtml2pdf' a requirements.txt e instala dependencias.")

    template = loader.get_template(template_name)
    html = template.render(context)

    result = BytesIO()
    pisa_status = pisa.CreatePDF(src=html, dest=result, encoding='utf-8')
    if pisa_status.err:
        raise RuntimeError("Error generando PDF: xhtml2pdf reportó errores")
    return result.getvalue()


def build_pdf_response(pdf_bytes: bytes, filename: str) -> HttpResponse:
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
