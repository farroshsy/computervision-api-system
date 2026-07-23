"""Multi-document splitting for wallet photos (KTP + SIM in one frame).

4 of 20 real KYC photos contain two stacked documents. When type
detection is ambiguous (two types score strongly), we re-read the image
once WITH text-box coordinates, split lines into vertical clusters at
large gaps, and detect+parse each cluster separately.

Used only when needed: single-document photos never pay for this.
"""
import logging
import os
import tempfile
from typing import Dict, List, Optional

import cv2
import numpy as np

from app.services.paddle_ocr import ocr_service
from app.utils.detection import detect_document_type_detailed
from app.schemas.request_models import DocumentType

logger = logging.getLogger(__name__)

# A vertical gap this many times the median line height splits clusters
GAP_FACTOR = 1.8


def ocr_lines_with_boxes(image_bytes: bytes) -> List[Dict]:
    """One plain OCR pass returning [{text, conf, x0, x1, cy, h}] sorted by cy.

    x0/x1 are what spatial_pairing needs to read a value to the RIGHT of its
    label; without them a split document can only be parsed by the weak
    text-order path.
    """
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return []
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        cv2.imwrite(path, img)
        result = ocr_service.run_ocr(path)
    except Exception as e:
        logger.warning("Box OCR failed: %s", str(e))
        return []
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    items: List[Dict] = []
    for line in (result[0] or []) if result else []:
        try:
            box, (text, conf) = line[0], line[1]
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            items.append({
                "text": str(text).strip(),
                "conf": float(conf),
                "x0": min(xs),
                "x1": max(xs),
                "cy": (min(ys) + max(ys)) / 2.0,
                "h": max(ys) - min(ys),
                "y0": min(ys),
                "y1": max(ys),
            })
        except (IndexError, TypeError, ValueError):
            continue
    items.sort(key=lambda it: it["cy"])
    return items


def cluster_bbox(cluster: List[Dict], pad_frac: float = 0.04) -> Optional[Dict]:
    """Pixel box enclosing a cluster, padded — used to crop the sub-document
    so the trained field detector can run on it like a single-doc image."""
    if not cluster:
        return None
    x0 = min(it["x0"] for it in cluster)
    x1 = max(it["x1"] for it in cluster)
    y0 = min(it.get("y0", it["cy"] - it["h"] / 2) for it in cluster)
    y1 = max(it.get("y1", it["cy"] + it["h"] / 2) for it in cluster)
    pad_x = (x1 - x0) * pad_frac
    pad_y = (y1 - y0) * pad_frac
    return {"x0": x0 - pad_x, "y0": y0 - pad_y, "x1": x1 + pad_x, "y1": y1 + pad_y}


def crop_to_png(image_bytes: bytes, bbox: Dict) -> Optional[bytes]:
    """Crop bbox out of the original image and re-encode as PNG bytes."""
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return None
        h, w = img.shape[:2]
        x0 = max(0, int(bbox["x0"]))
        y0 = max(0, int(bbox["y0"]))
        x1 = min(w, int(bbox["x1"]))
        y1 = min(h, int(bbox["y1"]))
        if x1 - x0 < 20 or y1 - y0 < 20:
            return None
        ok, buf = cv2.imencode(".png", img[y0:y1, x0:x1])
        return buf.tobytes() if ok else None
    except Exception as e:
        logger.warning("Sub-document crop failed: %s", str(e))
        return None


def split_vertical_clusters(items: List[Dict]) -> List[List[Dict]]:
    """Split sorted line items where the vertical gap is unusually large."""
    if len(items) < 4:
        return [items] if items else []
    heights = sorted(it["h"] for it in items if it["h"] > 0)
    med_h = heights[len(heights) // 2] if heights else 20.0
    clusters: List[List[Dict]] = [[items[0]]]
    for prev, cur in zip(items, items[1:]):
        if cur["cy"] - prev["cy"] > GAP_FACTOR * med_h + med_h:
            clusters.append([cur])
        else:
            clusters[-1].append(cur)
    return clusters


def try_split_documents(image_bytes: bytes, hint_types: Optional[List[str]] = None) -> Optional[List[Dict]]:
    """Attempt to split a photo into multiple typed documents.

    Returns a list of {"document_type", "lines", "detection"} — one entry
    per confidently-typed cluster — when at least two DIFFERENT document
    types are found. Returns None when the photo doesn't split cleanly
    (caller keeps its single-document behaviour).

    hint_types: types the PHOTO-LEVEL detection already scored strongly.
    A cluster whose own evidence is weaker (e.g. the document title
    garbled) may adopt its top-scoring type when that type is among the
    hints — the photo as a whole already proved the type is present.
    """
    items = ocr_lines_with_boxes(image_bytes)
    if len(items) < 6:
        return None
    clusters = split_vertical_clusters(items)
    if len(clusters) < 2:
        return None

    hints = {h.upper() for h in (hint_types or [])}
    typed: List[Dict] = []
    for cluster in clusters:
        kept = [it for it in cluster if it["conf"] > 0.25]
        lines = [it["text"] for it in kept]
        if len(lines) < 3:
            continue
        det = detect_document_type_detailed(lines)
        entry = {"lines": lines, "items": kept, "detection": det}
        if det["doc_type"] not in (DocumentType.UNKNOWN, DocumentType.AUTO):
            entry["document_type"] = det["doc_type"]
            typed.append(entry)
            continue
        if hints:
            top_type, top_score = max(det["scores"].items(), key=lambda kv: kv[1])
            if top_type in hints and top_score >= 2.0:
                det["doc_type"] = DocumentType(top_type)
                entry["document_type"] = det["doc_type"]
                typed.append(entry)

    # Merge adjacent clusters that resolved to the same type (a document
    # with internal whitespace must not become two half-documents)
    merged: List[Dict] = []
    for entry in typed:
        if merged and merged[-1]["document_type"] == entry["document_type"]:
            merged[-1]["lines"].extend(entry["lines"])
            merged[-1]["items"].extend(entry["items"])
            merged[-1]["detection"] = detect_document_type_detailed(merged[-1]["lines"])
        else:
            merged.append(entry)

    for entry in merged:
        entry["bbox"] = cluster_bbox(entry["items"])

    distinct = {e["document_type"] for e in merged}
    if len(distinct) < 2:
        return None
    return merged
