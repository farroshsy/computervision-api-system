"""PDF input support: scanned documents often arrive as PDFs
(the KYC archive contains them). The first page is rendered to an
image and the normal pipeline takes over.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

RENDER_SCALE = 2.8  # ~200 DPI for a typical A4 scan


def is_pdf(data: bytes) -> bool:
    return bool(data) and data[:5] == b"%PDF-"


def pdf_first_page_to_png(data: bytes) -> Optional[bytes]:
    """Render page 1 of a PDF to PNG bytes; None when rendering fails."""
    try:
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(data)
        try:
            if len(doc) < 1:
                return None
            page = doc[0]
            bitmap = page.render(scale=RENDER_SCALE)
            pil = bitmap.to_pil()
        finally:
            doc.close()
        import io
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.warning("PDF rendering failed: %s", e)
        return None


def normalize_upload(data: bytes) -> bytes:
    """PDF bytes -> first-page PNG bytes; anything else passes through."""
    if is_pdf(data):
        rendered = pdf_first_page_to_png(data)
        if rendered is not None:
            return rendered
    return data
