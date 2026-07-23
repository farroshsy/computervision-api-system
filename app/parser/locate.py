"""Where on the page did each value come from?

The customer's own spec (Logisly, "OCR Sample") does not describe fields as a
list — it draws a NUMBERED BOX around each one on a photo of the document. That
is the shape of the answer they asked for, and until now the API threw the
geometry away: the trained detector locates a field visually, crops it, OCRs the
crop, and then returns the text with no coordinates at all.

Rather than thread a box through every extraction stage (rule, spatial pairing,
detector, spec fields), this runs ONCE at the end and matches each final value
back to the OCR line it came from. One pass covers every stage and every
document type — including KIR and SIM, which have no detector weights.

A box is evidence, not decoration: it lets a reviewer see *where* a value was
read from, which is exactly what turns a needs_review flag into a two-second
human check. When a value cannot be traced back to a line, it gets no box —
never a guessed one.
"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Values too short to locate unambiguously: "B" or "II" would match half the
# page. A box on the wrong row is worse than no box.
_MIN_MATCH_LEN = 3


def _norm(s: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _item_box(it: Dict) -> Tuple[float, float, float, float]:
    """(x0, y0, x1, y1) — items carry cy/h rather than y0/y1."""
    h = float(it.get("h") or 0.0)
    cy = float(it.get("cy") or 0.0)
    y0 = it.get("y0")
    y1 = it.get("y1")
    if y0 is None or y1 is None:
        y0, y1 = cy - h / 2.0, cy + h / 2.0
    return float(it["x0"]), float(y0), float(it["x1"]), float(y1)


def _union(boxes: List[Tuple[float, float, float, float]]):
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


def _locate_value(value: str, items: List[Dict]) -> Optional[Tuple[float, float, float, float]]:
    """The box of the OCR line(s) this value was read from, if traceable."""
    v = _norm(value)
    if len(v) < _MIN_MATCH_LEN:
        return None

    # 1. one line contains the whole value ("BERLAKU SAMPAI:13-06-2025" holds
    #    "13-06-2025"). Prefer the TIGHTEST such line — the shortest match is
    #    the one that is mostly the value itself rather than a whole row.
    containing = [it for it in items if v and v in _norm(it.get("text"))]
    if containing:
        best = min(containing, key=lambda it: len(_norm(it.get("text"))))
        return _item_box(best)

    # 2. the value was assembled from several lines on the same row
    #    ("TRK" "TRONTON" "BOX"), which is how Paddle emits a spaced value.
    parts = [it for it in items
             if len(_norm(it.get("text"))) >= 2 and _norm(it.get("text")) in v]
    if parts:
        # only lines that sit on the same visual row as the tallest match
        anchor = max(parts, key=lambda it: len(_norm(it.get("text"))))
        row_tol = max(float(anchor.get("h") or 12.0), 12.0) * 0.9
        row = [it for it in parts
               if abs(float(it.get("cy") or 0) - float(anchor.get("cy") or 0)) <= row_tol]
        covered = "".join(_norm(it.get("text")) for it in
                          sorted(row, key=lambda it: float(it["x0"])))
        # require the row to actually account for most of the value, else the
        # box would be drawn around a coincidence
        if len(covered) >= max(_MIN_MATCH_LEN, int(0.6 * len(v))):
            return _union([_item_box(it) for it in row])
    return None


def attach_bboxes(fields: Dict[str, Any], items: List[Dict],
                  image_size: Optional[Tuple[int, int]] = None) -> Dict[str, Any]:
    """Add `bbox` to every field whose value can be traced to an OCR line.

    Pixel coordinates, plus normalized 0..1 so a caller can draw the box on any
    rendering of the image without knowing the original resolution.
    """
    if not isinstance(fields, dict) or not items:
        return fields
    w, h = (image_size or (0, 0))
    for key, rec in fields.items():
        if not isinstance(rec, dict) or rec.get("bbox"):
            continue
        box = _locate_value(rec.get("value"), items)
        if not box:
            continue
        x0, y0, x1, y1 = box
        bbox = {"x0": round(x0), "y0": round(y0), "x1": round(x1), "y1": round(y1)}
        if w and h:
            bbox["norm"] = {
                "x0": round(max(0.0, min(1.0, x0 / w)), 4),
                "y0": round(max(0.0, min(1.0, y0 / h)), 4),
                "x1": round(max(0.0, min(1.0, x1 / w)), 4),
                "y1": round(max(0.0, min(1.0, y1 / h)), 4),
            }
        rec["bbox"] = bbox
    return fields


def image_size_of(image_bytes: bytes) -> Optional[Tuple[int, int]]:
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return None
        return int(img.shape[1]), int(img.shape[0])
    except Exception:
        return None
