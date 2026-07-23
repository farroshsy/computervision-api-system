"""QR decoding: KIR (BLU-e) cards carry authoritative Kemenhub QR codes."""
import cv2
import numpy as np
import qrcode

from app.utils.qr_reader import decode_qr_codes


def _doc_with_qr(payload: str) -> bytes:
    qr_img = qrcode.make(payload).convert("RGB")
    qr = cv2.cvtColor(np.array(qr_img), cv2.COLOR_RGB2BGR)
    # place QR top-right on a KIR-like page
    page = np.full((1000, 760, 3), 235, dtype=np.uint8)
    cv2.putText(page, "KARTU UJI BERKALA", (30, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
    qr_small = cv2.resize(qr, (250, 250))
    page[30:280, 480:730] = qr_small
    ok, enc = cv2.imencode(".png", page)
    assert ok
    return enc.tobytes()


def test_decodes_kir_style_qr():
    payload = "https://blue.dephub.go.id/verifikasi/BBO41642201"
    codes = decode_qr_codes(_doc_with_qr(payload))
    assert payload in codes


def test_no_qr_returns_empty():
    page = np.full((400, 400, 3), 255, dtype=np.uint8)
    ok, enc = cv2.imencode(".png", page)
    assert decode_qr_codes(enc.tobytes()) == []


def test_garbage_bytes_return_empty():
    assert decode_qr_codes(b"not an image") == []
