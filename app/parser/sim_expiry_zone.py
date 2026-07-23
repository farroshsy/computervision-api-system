"""Zone re-read for a MISSING SIM expiry date.

The full-frame OCR sometimes reads only a fragment of the expiry
("1024" out of "01-07-2024") — the field then comes back empty even on
a good photo. This recovers it by re-reading a window around that
digit fragment at 2x.

Why this is NOT the rejected crop-re-OCR idea: it only FILLS an EMPTY
field (never replaces a read), the result must be a complete
DD-MM-YYYY date in a plausible year window, and the window is anchored
on an actual OCR box — three gates a hallucinated read has to pass.

Rotation: the OCR pipeline auto-orients the page internally, so item
coordinates live in the ORIENTED frame while we only hold the raw
image. Rather than plumbing the oriented image out of the pipeline, try
the 4 rotations — only the right one puts the fragment under the crop;
the wrong ones yield no valid date and are rejected by the gates.
"""
import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

_FULL_DATE = re.compile(r"\b(\d{2}[-/.]\d{2}[-/.](?:19|20)\d{2})\b")


def _digit_fragments(items: List[Dict]) -> List[Dict]:
    """Bottom-half boxes holding a short digit run but no complete date —
    the classic partially-read expiry."""
    max_cy = max((it["cy"] for it in items), default=0.0)
    out = []
    for it in items:
        text = it["text"]
        if it["cy"] < 0.5 * max_cy or _FULL_DATE.search(text):
            continue
        digits = re.sub(r"[^0-9]", "", text)
        if 4 <= len(digits) <= 8:
            out.append(it)
    out.sort(key=lambda it: -it["cy"])
    return out[:2]


def recover_sim_expiry(image_bytes: bytes, items: List[Dict], fields: Dict) -> Dict:
    """Fill fields['expiry_date'] from a zone re-read; no-op unless empty."""
    for key in ("expiry_date", "valid_to"):
        rec = fields.get(key)
        if (rec.get("value") if isinstance(rec, dict) else rec):
            return fields
    if not items or not image_bytes:
        return fields
    anchors = _digit_fragments(items)
    if not anchors:
        return fields
    try:
        import cv2
        import numpy as np
        from app.parser.field_detector import _ocr_crop
        from app.utils.validators import normalize_expiry_date
    except Exception:
        return fields
    raw = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if raw is None:
        return fields
    rotations = (None, cv2.ROTATE_90_COUNTERCLOCKWISE,
                 cv2.ROTATE_90_CLOCKWISE, cv2.ROTATE_180)
    for anchor in anchors:
        for rot in rotations:
            img = raw if rot is None else cv2.rotate(raw, rot)
            x0 = int(max(0, anchor["x0"] - 320))
            x1 = int(min(img.shape[1], anchor["x1"] + 120))
            y0 = int(max(0, anchor["cy"] - 45))
            y1 = int(min(img.shape[0], anchor["cy"] + 45))
            if x1 - x0 < 60 or y1 - y0 < 20:
                continue
            crop = cv2.resize(img[y0:y1, x0:x1], None, fx=2, fy=2,
                              interpolation=cv2.INTER_CUBIC)
            try:
                text = _ocr_crop(crop)
            except Exception:
                continue
            m = _FULL_DATE.search(text or "")
            if not m:
                continue
            iso = normalize_expiry_date(m.group(1))
            if not iso or not (2010 <= int(iso[:4]) <= 2040):
                continue
            fields["expiry_date"] = {"value": iso, "confidence": 0.6,
                                     "provenance": {"method": "zone_reocr"}}
            logger.info("sim expiry recovered by zone re-read")
            return fields
    return fields
