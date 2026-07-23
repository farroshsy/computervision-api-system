"""Mirror-rescue behavior of the OCR service (measured: mirrored uploads
read as nothing without it — robustness eval 0/20 detection)."""
import cv2
import numpy as np

from app.services.paddle_ocr import extract_text_from_image


def _text_image(mirrored: bool) -> bytes:
    img = np.full((240, 900, 3), 255, dtype=np.uint8)
    cv2.putText(img, "SURAT IZIN MENGEMUDI", (30, 100), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 4)
    cv2.putText(img, "1427-8708-000059", (30, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 4)
    if mirrored:
        img = cv2.flip(img, 1)
    ok, enc = cv2.imencode(".png", img)
    assert ok
    return enc.tobytes()


def test_mirrored_upload_is_rescued():
    lines = extract_text_from_image(_text_image(mirrored=True))
    joined = " ".join(lines).upper().replace(" ", "")
    assert "MENGEMUDI" in joined or "1427" in joined
