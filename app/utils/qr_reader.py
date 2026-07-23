"""QR code extraction from document photos.

Modern Indonesian documents carry QR codes with authoritative data:
- KIR (BLU-e) cards link to the official Kemenhub record — decoding the
  QR gives 100%-accurate data, no OCR guessing.
- New-format SIMs carry a QR as well.

Uses OpenCV's built-in detector (no extra dependency). Photos are often
low-resolution, so decoding is attempted at several scales.
"""
import logging
from typing import List, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_SCALES = (1.0, 1.5, 2.0, 0.75)


def decode_qr_codes(image_bytes: bytes) -> List[str]:
    """Return all decodable QR payloads in the image (may be empty).

    Best-effort: low-resolution photos frequently defeat QR decoding;
    an empty result only means nothing was decodable, not that no QR
    is present.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return []
    detector = cv2.QRCodeDetector()
    found: List[str] = []
    for scale in _SCALES:
        try:
            variant = img if scale == 1.0 else cv2.resize(
                img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            ok, texts, _, _ = detector.detectAndDecodeMulti(variant)
            if ok:
                for t in texts:
                    if t and t not in found:
                        found.append(t)
            if found:
                break
        except cv2.error as e:
            logger.debug("QR decode failed at scale %s: %s", scale, e)
            continue
    return found
