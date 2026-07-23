"""PDF input: scanned docs arrive as PDFs; first page renders to image."""
import io

import cv2
import numpy as np
from PIL import Image

from app.utils.pdf_input import is_pdf, normalize_upload


def _pdf_with_text(text: str) -> bytes:
    img = np.full((400, 800, 3), 255, dtype=np.uint8)
    cv2.putText(img, text, (30, 200), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 4)
    pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    buf = io.BytesIO()
    pil.save(buf, format="PDF")
    return buf.getvalue()


def test_is_pdf():
    assert is_pdf(b"%PDF-1.4 rest") is True
    assert is_pdf(b"\x89PNG") is False


def test_pdf_renders_and_pipeline_reads_it():
    pdf = _pdf_with_text("SURAT IZIN MENGEMUDI")
    out = normalize_upload(pdf)
    assert not is_pdf(out)
    arr = np.frombuffer(out, dtype=np.uint8)
    assert cv2.imdecode(arr, cv2.IMREAD_COLOR) is not None


def test_non_pdf_passes_through():
    data = b"\x89PNG fake"
    assert normalize_upload(data) is data


def test_endpoint_accepts_pdf(test_client):
    pdf = _pdf_with_text("SURAT IZIN MENGEMUDI")
    r = test_client.post("/api/v1/ocr/file",
                         files={"file": ("scan.pdf", io.BytesIO(pdf), "application/pdf")},
                         data={"document_type": "AUTO"})
    assert r.status_code == 200, r.text
    assert r.json()["document_type"] in ("SIM", "UNKNOWN")


def test_low_resolution_gets_retake_reason(test_client):
    import cv2
    import numpy as np

    tiny = np.full((300, 420, 3), 255, dtype=np.uint8)
    cv2.putText(tiny, "NIK 3201241107690002", (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    ok, enc = cv2.imencode(".jpg", tiny)
    r = test_client.post("/api/v1/ocr/file",
                         files={"file": ("tiny.jpg", io.BytesIO(enc.tobytes()), "image/jpeg")},
                         data={"document_type": "KTP"})
    assert r.status_code == 200
    assert "resolution_too_low" in r.json()["data"]["validation"]["reasons"]
