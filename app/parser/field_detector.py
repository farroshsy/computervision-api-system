"""Trained field-region detection (premium extraction path).

When YOLO-OBB weights are available (trained on community-labeled field
datasets), each document field is located VISUALLY, cropped, and OCR'd
individually — the value lands in the right field by detector class, not
by label-text guessing. This attacks the measured weak spots: STNK
owner/rangka association and KIR label pairing.

Fully optional: no ultralytics install or no weights -> silently
disabled, the rule-based extractors keep working unchanged.

Enable per type with env vars:
    FIELD_DETECTOR_STNK_WEIGHTS=./train_runs/stnk_fields/weights/best.pt
    FIELD_DETECTOR_KTP_WEIGHTS=./train_runs/ktp_fields/weights/best.pt
    FIELD_DETECTOR_SIM_WEIGHTS=./train_runs/sim_fields/weights/best.pt
    FIELD_DETECTOR_KIR_WEIGHTS=./train_runs/kir_fields/weights/best.pt

STNK/KTP weights come from community-labelled datasets; SIM/KIR from detectors
trained on synthetic cards (scripts/synth_cards.py + scripts/train_field_detector.py)
because no public per-field SIM/KIR box dataset exists and real photos carry
only text ground truth. Synthetic data is used ONLY to learn field positions;
accuracy is always measured on the real held-out samples.
"""
import logging
import os
import re
import tempfile
from typing import Dict, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# Dataset class names -> our field keys
CLASS_MAP = {
    "STNK": {
        "nomor_registrasi": "nomor_polisi",
        "nomor_rangka": "nomor_rangka",
        "nomor_mesin": "nomor_mesin",
        "berlaku_sampai": "tax_valid_to",
        "merk": "brand",
        "alamat": "alamat",
        "warna": "warna",
    },
    "KTP": {
        "nik": "nik",
        "nama": "nama",
        "alamat": "alamat",
        "agama": "agama",
        "jenisKel": "jenis_kelamin",
        "kecamatan": "kecamatan",
        "kel-desa": "kelurahan_desa",
        "pekerjaan": "pekerjaan",
        "tglLahir": "tanggal_lahir",
        "tmptLahir": "tempat_lahir",
        "goldar": "gol_darah",
    },
    # SIM/KIR detectors trained on synthetic cards (scripts/synth_cards.py):
    # the class name IS the field key, and the box wraps the VALUE (not the
    # label), so no rightward-extend crop trick is needed for these types.
    "SIM": {
        "nomor_sim": "nomor_sim",
        "nama": "nama",
        "tanggal_lahir": "tanggal_lahir",
        "alamat": "alamat",
        "masa_berlaku": "masa_berlaku",
        "tipe_sim": "tipe_sim",
    },
    "KIR": {
        "owner_name": "owner_name",
        "nomor_polisi": "nomor_polisi",
        "nomor_uji": "nomor_uji",
        "nomor_rangka": "nomor_rangka",
        "nomor_mesin": "nomor_mesin",
        "kubikasi": "kubikasi",
        "dimensi": "dimensi",
        "masa_berlaku": "masa_berlaku",
        "tgl_uji": "tgl_uji",
    },
}

_ENV_KEYS = {
    "STNK": "FIELD_DETECTOR_STNK_WEIGHTS",
    "KTP": "FIELD_DETECTOR_KTP_WEIGHTS",
    "SIM": "FIELD_DETECTOR_SIM_WEIGHTS",
    "KIR": "FIELD_DETECTOR_KIR_WEIGHTS",
}
_models: Dict[str, object] = {}


def _get_model(doc_type: str):
    """Lazy-load the YOLO model for doc_type; None when unavailable."""
    doc_type = doc_type.upper()
    if doc_type in _models:
        return _models[doc_type]
    weights = os.getenv(_ENV_KEYS.get(doc_type, ""), "")
    model = None
    if weights and os.path.exists(weights):
        try:
            from ultralytics import YOLO
            model = YOLO(weights)
            logger.info("Field detector loaded for %s: %s", doc_type, weights)
        except Exception as e:
            logger.warning("Field detector unavailable for %s: %s", doc_type, e)
    _models[doc_type] = model
    return model


def _extend_right(points: np.ndarray, img_w: int, factor: float = 3.0) -> np.ndarray:
    """Stretch a box horizontally to the right by factor x its width."""
    pts = points.copy().astype(np.float32)
    x_min, x_max = pts[:, 0].min(), pts[:, 0].max()
    w = max(x_max - x_min, 1.0)
    new_x_max = min(img_w - 1.0, x_min + w * factor)
    pts[:, 0] = np.where(pts[:, 0] > (x_min + x_max) / 2, new_x_max, pts[:, 0])
    return pts


def _crop_obb(img: np.ndarray, points: np.ndarray, pad: int = 4) -> Optional[np.ndarray]:
    """Perspective-rectify an oriented box to an axis-aligned crop."""
    rect = cv2.minAreaRect(points.astype(np.float32))
    (cx, cy), (w, h), angle = rect
    if w < 4 or h < 4:
        return None
    # keep text horizontal: treat the longer side as width
    if w < h:
        w, h = h, w
        angle += 90
    w, h = int(w) + 2 * pad, int(h) + 2 * pad
    src = cv2.boxPoints(((cx, cy), (w, h), angle))
    dst = np.array([[0, h - 1], [0, 0], [w - 1, 0], [w - 1, h - 1]], dtype=np.float32)
    m = cv2.getPerspectiveTransform(src.astype(np.float32), dst)
    return cv2.warpPerspective(img, m, (w, h))


def _ocr_crop(crop: np.ndarray) -> str:
    from app.services.paddle_ocr import ocr_service
    # small crops OCR better with some headroom
    if max(crop.shape[:2]) < 320:
        scale = 320 / max(crop.shape[:2])
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    fd, path = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    try:
        cv2.imwrite(path, crop)
        result = ocr_service.run_ocr(path)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    texts = [str(line[1][0]).strip() for line in (result[0] or []) if line[1][0]]
    return " ".join(texts).strip()


# Per-field value patterns applied to the crop's OCR text (which may
# contain the printed label words next to the value)
_VALUE_PATTERNS = {
    "nomor_polisi": re.compile(r"\b[A-Z]{1,2}[\s-]?\d{3,4}[\s-]?[A-Z]{1,3}\b"),
    "nomor_rangka": re.compile(r"\b[A-Z0-9]{15,17}\b"),
    "nomor_mesin": re.compile(r"\b(?=[A-Z0-9]*\d)[A-Z0-9]{8,12}\b"),
    "tax_valid_to": re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b"),
    "nik": re.compile(r"\b\d{16}\b"),
    "tanggal_lahir": re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b"),
    # SIM/KIR value shapes (box wraps the value; pattern strips stray neighbours
    # and lets a shape-valid detector hit beat a shape-invalid rule guess)
    "nomor_sim": re.compile(r"\b\d{3,4}-\d{3,4}-\d{4,6}\b"),
    "nomor_uji": re.compile(r"\b[A-Z]{0,3}\d{6,}\b"),
    "masa_berlaku": re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b"),
    "tgl_uji": re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{4}\b"),
}
# Printed label words to strip when no pattern applies
_LABEL_WORDS = re.compile(
    r"\b(NOMOR|REGISTRASI|VEHICLE|REGISTRATION|NUMBER|MESIN|ENGINE|RANGKA|CHASSIS|"
    r"NIK|VIN|BERLAKU|SAMPAI|DATE|OF|EXPIRE?|MERK|BRAND|TYPE|WARNA|COLOU?RS?|COLON|"
    r"ALAMAT|ADDRESS|NAMA|NAME|TEMPAT|TGL|LAHIR|AGAMA|PEKERJAAN|JENIS|KELAMIN)\b[:.]?",
    re.IGNORECASE,
)


def _clean_field_value(key: str, text: str) -> str:
    """Reduce a label+value crop text to just the value."""
    if not text:
        return ""
    pattern = _VALUE_PATTERNS.get(key)
    if pattern:
        m = pattern.search(text.upper().replace(" ", "") if key in
                           ("nomor_rangka", "nik") else text.upper())
        if m:
            return m.group(0)
        return ""  # patterned fields: no match means unusable crop text
    cleaned = _LABEL_WORDS.sub(" ", text)
    return re.sub(r"\s+", " ", cleaned).strip(" :.-")


def detect_fields(image_bytes: bytes, doc_type: str) -> Optional[Dict[str, Dict]]:
    """Detect + OCR field regions. None when detector disabled/failed."""
    model = _get_model(doc_type)
    if model is None:
        return None
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        return None
    try:
        results = model.predict(img, verbose=False, conf=0.4)
    except Exception as e:
        logger.warning("Field detector inference failed: %s", e)
        return None
    mapping = CLASS_MAP.get(doc_type.upper(), {})
    fields: Dict[str, Dict] = {}
    for res in results:
        obb = getattr(res, "obb", None)
        if obb is None:
            continue
        names = res.names
        for i in range(len(obb.cls)):
            cls_name = names[int(obb.cls[i])]
            key = mapping.get(cls_name)
            if key is None:
                continue
            conf = float(obb.conf[i])
            # keep the highest-confidence detection per field
            if key in fields and fields[key]["confidence"] >= conf:
                continue
            points = obb.xyxyxyxy[i].cpu().numpy().reshape(4, 2)
            if doc_type.upper() == "STNK":
                # this dataset boxes the LABEL text; the value sits to the
                # right of it on STNK rows — extend the crop rightward
                points = _extend_right(points, img.shape[1], factor=3.0)
            crop = _crop_obb(img, points)
            if crop is None:
                continue
            text = _clean_field_value(key, _ocr_crop(crop))
            if text:
                fields[key] = {
                    "value": text,
                    "confidence": round(conf, 3),
                    "provenance": {"method": "field_detector", "class": cls_name},
                }
    return fields or None


# Rule methods that are guesses (shape/regex fallbacks) — a confident
# detector hit may REPLACE these; label-extracted values are kept.
_REPLACEABLE_METHODS = {"vin_shape", "engine_shape", "cert_shape", "regex_minimal"}


def enrich_with_detector(doc_type: str, image_bytes: bytes, fields: Dict) -> Dict:
    """Fill missing fields from the detector; replace low-trust rule
    guesses when the detector is confident; never touch label-extracted
    values."""
    detected = detect_fields(image_bytes, doc_type)
    if not detected:
        return fields
    for key, rec in detected.items():
        existing = fields.get(key)
        existing_val = existing.get("value") if isinstance(existing, dict) else existing
        if not existing_val:
            fields[key] = rec
            continue
        if isinstance(existing, dict) and rec["confidence"] >= 0.5:
            method = (existing.get("provenance") or {}).get("method", "")
            if method in _REPLACEABLE_METHODS and float(existing.get("confidence", 1.0)) <= 0.7:
                fields[key] = rec
                continue
            # pattern-valid beats pattern-invalid: rule extractors sometimes
            # capture label text ("NIK/VIN") or stray tokens ("NO 3 RT") with
            # high confidence — if the detector value matches the field's
            # shape and the existing value does not, trust the detector
            pattern = _VALUE_PATTERNS.get(key)
            if pattern is not None:
                det_ok = bool(pattern.search(str(rec["value"]).upper().replace(" ", "") if key in ("nomor_rangka", "nik") else str(rec["value"]).upper()))
                old_ok = bool(pattern.search(str(existing_val).upper().replace(" ", "") if key in ("nomor_rangka", "nik") else str(existing_val).upper()))
                if det_ok and not old_ok:
                    fields[key] = rec
    return fields
