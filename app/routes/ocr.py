"""OCR API endpoints for document processing."""
import logging
import time
import traceback
from typing import Dict, Any, List, Optional
import numpy as np
import cv2
from pydantic import ConfigDict

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    HTTPException,
    Request,
    Response,
    Depends,
    status,
    Form,
    Query,
)
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, HttpUrl, Field

# Import services and utilities
from app.services.paddle_ocr import extract_text_from_image
from app.parser.ktp_parser.ktp_parser import parse_ktp_fields
from app.models.schemas import ParserContext
from app.parser.sim_parser.sim_extractor import SIMExtractor
from app.parser.stnk_parser.stnk_extractor import STNKExtractor
from app.parser.kir_parser.kir_extractor import KIRExtractor
from app.parser.spec_fields import (derive_aliases, journal_begin,
                                    journal_entries, strip_label_residue,
                                    validate_fields)
from app.monitoring.metrics import metrics, record_ocr_metrics
from app.middleware.rate_limiter import rate_limit
from app.schemas.request_models import DocumentType, FileUploadRequest, URLRequest, OCRResponse
from app.utils.validation import validate_file_upload, validate_document_type
from app.utils.detection import detect_document_type, detect_document_type_detailed
from app.utils.id_reference import fuzzy_correct_fields, nik_cross_check
from app.config import settings
from app.models.document_schemas import SIMDocument, STNKDocument, KIRDocument
from pydantic import ValidationError
from app.utils.validators import (
    normalize_nik,
    normalize_dob,
    normalize_plate,
    normalize_chassis,
    normalize_engine,
    normalize_expiry_date,
    normalize_rt_rw,
)
from app.pipeline.pipeline_cascade import CascadePipeline

logger = logging.getLogger(__name__)
# Create router without rate limiting as a dependency
router = APIRouter(
    prefix="/api/v1",
    tags=["ocr"]
)

# Apply rate limiting to specific routes instead of the entire router

class OCRRequest(BaseModel):
    """
    Base model for OCR requests.
    
    Attributes:
        document_type: Type of document to process (KTP, SIM, STNK, KIR)
        confidence_threshold: Minimum confidence score (0.0-1.0) for text extraction
    """
    document_type: DocumentType = Field(
        ...,
        description="Type of document to process",
        json_schema_extra={"example": "KTP"}
    )
    confidence_threshold: Optional[float] = Field(
        0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for text extraction (0.0-1.0)",
        json_schema_extra={"example": 0.7}
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_type": "KTP",
                "confidence_threshold": 0.7
            }
        }
    )

class FileOCRRequest(OCRRequest):
    """
    Model for file-based OCR requests.
    
    Inherits from OCRRequest and adds file upload capability.
    """
    file: UploadFile = Field(
        ...,
        description="Image file to process (JPEG, PNG, or WebP)",
        json_schema_extra={"example": "<binary file data>"}
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_type": "KTP",
                "confidence_threshold": 0.7,
                "file": "<binary file data>"
            }
        }
    )

class URLOcrRequest(OCRRequest):
    """
    Model for URL-based OCR requests.
    
    Inherits from OCRRequest and adds URL capability for remote image processing.
    """
    image_url: HttpUrl = Field(
        ...,
        description="URL of the image to process",
        json_schema_extra={"example": "https://example.com/document.jpg"}
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_type": "KTP",
                "confidence_threshold": 0.7,
                "image_url": "https://example.com/document.jpg"
            }
        }
    )

# --- Internal helper to dispatch to specific parsers ---
def _dispatch_parse(document_type: DocumentType, lines: List[str]) -> Dict[str, Any]:
    if document_type == DocumentType.KTP:
        # Legacy KTP parser expects list[str], returns dict of fields
        return {"fields": parse_ktp_fields(lines)}
    ctx = ParserContext(raw_lines=lines, debug=False)
    if document_type == DocumentType.SIM:
        return SIMExtractor().parse(ctx)
    if document_type == DocumentType.STNK:
        return STNKExtractor().parse(ctx)
    if document_type == DocumentType.KIR:
        return KIRExtractor().parse(ctx)
    return {"fields": {}}

def _sub_image(image_bytes: bytes, bbox: Optional[Dict[str, float]]) -> Optional[bytes]:
    """Crop one sub-document out of a wallet photo, for the field detector."""
    if not bbox:
        return None
    try:
        from app.parser.multi_doc import crop_to_png
        return crop_to_png(image_bytes, bbox)
    except Exception:
        return None


async def _enrich_fields(
    doc_type: DocumentType,
    lines: List[str],
    items: List[Dict[str, Any]],
    fields: Dict[str, Any],
    image_bytes: Optional[bytes] = None,
    detection_confidence: float = 0.0,
) -> Dict[str, Any]:
    """Every post-parse stage, in one place.

    The single-document and MULTI paths both call this. They used to run
    different subsets of the pipeline — MULTI skipped geometry and the trained
    detector entirely — which is why split wallet photos came back with no
    fields at all.
    """
    dt = doc_type.value if hasattr(doc_type, "value") else str(doc_type)

    # Geometry: pair each printed label with the value beside it.
    try:
        if items and dt in ("KIR", "STNK", "KTP", "SIM"):
            from app.parser.spatial_pairing import pair_fields_spatially
            fields = pair_fields_spatially(dt, items, fields)
    except Exception:
        logger.exception("spatial pairing failed for %s", dt)

    # SIM expiry zone re-read: fills an EMPTY expiry from a digit anchor.
    try:
        if dt == "SIM" and items and image_bytes:
            from app.parser.sim_expiry_zone import recover_sim_expiry
            fields = await run_in_threadpool(recover_sim_expiry, image_bytes, items, fields)
    except Exception:
        logger.exception("SIM expiry recovery failed")

    # Clear impossible values BEFORE the detector runs. The detector declines to
    # overwrite a field that is already populated with a higher confidence, so a
    # confidently-misread NIK ("5666650110820220" — no such province) squatted in
    # the slot, the detector left it alone, and validation deleted it afterwards:
    # the page ended up with NO nik even though the detector could read it.
    # Validating first empties the slot, so the detector gets to fill it.
    try:
        fields = validate_fields(dt, fields)
    except Exception:
        logger.exception("pre-detector validation failed for %s", dt)

    # Trained field detector. STNK/KTP use community-labelled datasets; SIM/KIR
    # use detectors trained on synthetic cards (scripts/synth_cards.py). Each is
    # gated on its FIELD_DETECTOR_<TYPE>_WEIGHTS env var — _get_model returns
    # None when the weights are absent, so this no-ops until a detector exists.
    try:
        if dt in ("STNK", "KTP", "SIM", "KIR") and image_bytes:
            from app.parser.field_detector import enrich_with_detector
            fields = await run_in_threadpool(enrich_with_detector, dt, image_bytes, fields)
    except Exception:
        logger.exception("field detector failed for %s", dt)

    # Spec fields the extractors never produced.
    try:
        from app.parser.spec_fields import (extract_title, extract_kir_spec_fields,
                                            extract_stnk_spec_fields,
                                            extract_ktp_spec_fields,
                                            recover_plate_from_lines)
        fields = extract_title(dt, lines, fields, detection_confidence)
        if dt == "KIR":
            fields = extract_kir_spec_fields(lines, fields)
        elif dt == "STNK":
            fields = extract_stnk_spec_fields(lines, fields)
        elif dt == "KTP":
            fields = extract_ktp_spec_fields(lines, fields)
        if dt in ("STNK", "KIR"):
            # plate printed far from its label; recover it from a valid-region
            # token when geometry+validation left the slot empty
            fields = recover_plate_from_lines(lines, fields)
    except Exception:
        logger.exception("spec field extraction failed for %s", dt)

    return fields


def _normalize_parsed_payload(raw_text: List[str], payload: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure data.fields is consistently shaped.
    - If a field value is a plain string, wrap as {"value": str, "confidence": 1.0}
    - If already dict with value/confidence, keep as is.
    Returns a dict suitable for OCRResponse.data
    """
    fields = payload.get("fields") or {}
    norm_fields: Dict[str, Any] = {}
    for k, v in fields.items():
        if isinstance(v, dict) and ("value" in v or "confidence" in v):
            norm_fields[k] = v
        else:
            norm_fields[k] = {"value": v, "confidence": 1.0}
    return {
        "raw_text": raw_text,
        "fields": norm_fields,
    }


def _regex_fallback_fields(doc_type: DocumentType, raw_text: List[str], fields: Dict[str, Any]) -> Dict[str, Any]:
    """Lightweight regex-based extraction to fill key fields when parsers miss.
    Only adds a field if it's currently missing or empty.
    """
    try:
        import re
        # Build helpers
        def missing(key: str) -> bool:
            v = fields.get(key)
            if v is None:
                return True
            if isinstance(v, dict):
                return not (v.get("value") or "")
            return not v

        def set_field(key: str, value: str, conf: float = 0.6):
            if not value:
                return
            if isinstance(fields.get(key), dict):
                fields.setdefault(key, {})["value"] = value
                fields[key]["confidence"] = fields[key].get("confidence", conf)
            else:
                fields[key] = {"value": value, "confidence": conf}

        # Create paired original/upper lines for matching
        lines = raw_text or []
        pairs = [(ln, (ln or "").upper()) for ln in lines]

        if doc_type == DocumentType.SIM:
            # Name
            if missing("name") and missing("nama"):
                for orig, up in pairs:
                    m = re.search(r"^\s*(?:\d{1,2}\s*[\.|\)]\s*)?\b(?:NAMA(?:/\s*NAME)?|NAMA\s+LENGKAP|NAME)\b\s*[:\-]?\s*(.+)$", up)
                    if m:
                        set_field("name", (orig[m.start(1):m.end(1)]).strip())
                        break
                # Fallback: enumerated position '1.' line often holds the name even without label
                if missing("name"):
                    for idx, (orig, up) in enumerate(pairs):
                        m = re.match(r"^\s*1\s*[\.|\)-]?\s*(.+)$", up)
                        if m:
                            cand = (orig[m.start(1):m.end(1)]).strip()
                            # must look like a name, not the SIM number line
                            # ("1427-8708-000059" also starts with '1')
                            if len(re.findall(r"[A-Za-z]", cand)) >= 3 and not re.search(r"\d{4,}", cand):
                                set_field("name", cand)
                                break
            # Address
            if missing("address") and missing("alamat"):
                for orig, up in pairs:
                    m = re.search(r"^\s*(?:\d{1,2}\s*[\.|\)]\s*)?\b(?:ALAMAT(?:/\s*ADDRESS)?|ADDRESS)\b\s*[:\-]?\s*(.+)$", up)
                    if m:
                        set_field("address", (orig[m.start(1):m.end(1)]).strip())
                        break
                # Fallback: enumerated position '4.' line commonly starts the address
                if missing("address"):
                    for idx in range(len(pairs)):
                        orig, up = pairs[idx]
                        m = re.match(r"^\s*4\s*[\.|\)-]?\s*(.+)$", up)
                        if m:
                            addr = (orig[m.start(1):m.end(1)]).strip()
                            # Optional: include next line if it's a continuation (not starting with next number)
                            if idx + 1 < len(pairs):
                                next_orig, next_up = pairs[idx + 1]
                                if not re.match(r"^\s*\d{1,2}\s*[\.|\)-]", next_up) and (next_orig or '').strip():
                                    addr = (addr + " " + next_orig.strip()).strip()
                            set_field("address", addr)
                            break
            # Expiry date
            if missing("expiry_date"):
                for orig, up in pairs:
                    # Allow enumerated labels (e.g., "13. BERLAKU S/D") and 2-digit year dates
                    m = re.search(
                        r"^\s*(?:\d{1,2}\s*[\.|\)]\s*)?\b(?:BERLAKU\s*S/?D|VALID\s*UNTIL|VALID\s*THRU|MASA\s*BERLAKU|BERLAKU\s*HINGGA|EXP)\b[^0-9]*(" \
                        r"(?:[0-9]{2}[\-/\.][0-9]{2}[\-/\.](?:[0-9]{2}|[0-9]{3}|[0-9]{4})|" \
                        r"(?:[0-9]{2}|[0-9]{3}|[0-9]{4})[\-/\.][0-9]{2}[\-/\.][0-9]{2})",
                        up,
                    )
                    if m:
                        set_field("expiry_date", (orig[m.start(1):m.end(1)]).strip())
                        break
                # Fallback: a bare date line after enumeration (e.g., '13. 01-07-2025')
                if missing("expiry_date"):
                    for orig, up in pairs:
                        m = re.match(r"^\s*1[23]\s*[\.|\)-]?\s*([0-9]{2}[\-/\.][0-9]{2}[\-/\.](?:[0-9]{2}|[0-9]{3}|[0-9]{4}))\s*$", up)
                        if m:
                            set_field("expiry_date", (orig[m.start(1):m.end(1)]).strip())
                            break
            # ID number (heuristic)
            if missing("id_number"):
                for orig, up in pairs:
                    m = re.search(r"^\s*(?:\d{1,2}\s*[\.|\)]\s*)?\b(?:NO\.?\s*(?:SIM|LISENSI)?|NOMOR\s*(?:SIM|LISENSI))\s*[:\-]?\s*([A-Z0-9]{8,20})\b", up)
                    if m:
                        set_field("id_number", (orig[m.start(1):m.end(1)]).strip())
                        break
            if missing("nomor_mesin"):
                for orig, up in pairs:
                    m = re.search(r"(?:NO\.?\s*MESIN|NOMOR\s*MESIN|MESIN|ENGINE)\s*[:\-]?\s*([A-Z0-9\-]+)", up)
                    if m:
                        set_field("nomor_mesin", (orig[m.start(1):m.end(1)]).strip())
                        break
        elif doc_type == DocumentType.KIR:
            if missing("nomor_rangka"):
                for orig, up in pairs:
                    m = re.search(r"(?:NO\.?\s*RANGKA|NOMOR\s*RANGKA|RANGKA|FRAME)\s*[:\-]?\s*([A-Z0-9\-]+)", up)
                    if m:
                        set_field("nomor_rangka", (orig[m.start(1):m.end(1)]).strip())
                        break
            if missing("nomor_mesin"):
                for orig, up in pairs:
                    m = re.search(r"(?:NO\.?\s*MESIN|NOMOR\s*MESIN|MESIN|ENGINE)\s*[:\-]?\s*([A-Z0-9\-]+)", up)
                    if m:
                        set_field("nomor_mesin", (orig[m.start(1):m.end(1)]).strip())
                        break
            if missing("masa_berlaku"):
                for orig, up in pairs:
                    m = re.search(r"(?:MASA\s*BERLAKU|BERLAKU\s*S/?D|VALID\s*UNTIL|VALID\s*THRU)[^0-9]*([0-9]{2}[\-/][0-9]{2}[\-/][0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})", up)
                    if m:
                        set_field("masa_berlaku", (orig[m.start(1):m.end(1)]).strip())
                        break
            if missing("tgl_uji"):
                for orig, up in pairs:
                    m = re.search(r"(?:TGL\.?|TANGGAL)\s*UJI[^0-9]*([0-9]{2}[\-/][0-9]{2}[\-/][0-9]{4}|[0-9]{4}-[0-9]{2}-[0-9]{2})", up)
                    if m:
                        set_field("tgl_uji", (orig[m.start(1):m.end(1)]).strip())
                        break
    except Exception:
        # Never let fallback parsing crash
        pass
    return fields

def _postprocess_fields(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Global, conservative fixes for known false positives across parsers.
    - Suppress alamat values that are clearly non-address administrative tokens like only 'RT/RW'.
    - Fuzzy-correct closed-vocabulary fields (agama, jenis_kelamin, ...)
      against Indonesian reference lexicons.
    """
    try:
        if not isinstance(fields, dict):
            return fields
        # Lexicon correction for closed-vocabulary fields (conservative:
        # only replaces on confident unambiguous match)
        fields = fuzzy_correct_fields(fields)

        alamat = fields.get("alamat")
        val = None
        if isinstance(alamat, dict):
            val = (alamat.get("value") or "").strip()
        elif isinstance(alamat, str):
            val = alamat.strip()
        if isinstance(val, str) and val:
            upper = val.upper().replace(" ", "")
            # Bare RT/RW label variants
            if upper in {"RT/RW", "RTRW"}:
                # suppress alamat
                if isinstance(alamat, dict):
                    fields.setdefault("alamat", {})["value"] = ""
            # Suppress label-only alamat leakage such as 'KEL/DESA' or 'KELURAHAN/DESA'
            if upper in {"KEL/DESA", "KELURAHAN/DESA", "KEL", "DESA", "KELURAHAN", "DESA/KEL", "DESA/KELURAHAN"}:
                if isinstance(alamat, dict):
                    fields.setdefault("alamat", {})["value"] = ""

        # Clean tempat_lahir artifacts (keep letters, spaces, and '-')
        tl = fields.get("tempat_lahir")
        tl_val = None
        if isinstance(tl, dict):
            tl_val = (tl.get("value") or "").strip()
        elif isinstance(tl, str):
            tl_val = tl.strip()
        if isinstance(tl_val, str) and tl_val:
            try:
                import re
                # Remove obvious OCR junk characters; collapse spaces
                cleaned = re.sub(r"[^A-Z\-\s]", "", tl_val.upper())
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                if isinstance(tl, dict):
                    fields.setdefault("tempat_lahir", {})["value"] = cleaned
            except Exception:
                pass
    except Exception:
        # Be conservative: never let postprocess crash the API
        pass
    # Second pass: conservative normalization for common keys (won't add new fields; only normalize if present)
    try:
        # NIK normalization
        if "nik" in fields:
            v = fields.get("nik")
            raw = (v.get("value") if isinstance(v, dict) else v)
            norm = normalize_nik(raw)
            if norm:
                if isinstance(v, dict):
                    fields["nik"]["value"] = norm
                else:
                    fields["nik"] = {"value": norm, "confidence": 1.0}
                try:
                    logger.debug("Normalized field", extra={"key": "nik", "raw": raw, "normalized": norm})
                except Exception:
                    pass
        # DOB normalization across common keys
        for k in ("tanggal_lahir", "tgl_lahir", "dob", "date_of_birth"):
            if k in fields:
                v = fields.get(k)
                raw = (v.get("value") if isinstance(v, dict) else v)
                normd = normalize_dob(raw)
                if normd:
                    if isinstance(v, dict):
                        fields[k]["value"] = normd
                    else:
                        fields[k] = {"value": normd, "confidence": 1.0}
                    try:
                        logger.debug("Normalized field", extra={"key": k, "raw": raw, "normalized": normd})
                    except Exception:
                        pass
        # Plate (STNK)
        if "plate_number" in fields:
            v = fields.get("plate_number")
            raw = (v.get("value") if isinstance(v, dict) else v)
            normp = normalize_plate(raw)
            if normp:
                if isinstance(v, dict):
                    fields["plate_number"]["value"] = normp
                else:
                    fields["plate_number"] = {"value": normp, "confidence": 1.0}
                try:
                    logger.debug("Normalized field", extra={"key": "plate_number", "raw": raw, "normalized": normp})
                except Exception:
                    pass
        # Chassis (STNK)
        if "chassis_number" in fields:
            v = fields.get("chassis_number")
            raw = (v.get("value") if isinstance(v, dict) else v)
            normc = normalize_chassis(raw)
            if normc:
                if isinstance(v, dict):
                    fields["chassis_number"]["value"] = normc
                else:
                    fields["chassis_number"] = {"value": normc, "confidence": 1.0}
                try:
                    logger.debug("Normalized field", extra={"key": "chassis_number", "raw": raw, "normalized": normc})
                except Exception:
                    pass
        # Engine (STNK/KIR)
        for k in ("engine_number", "nomor_mesin"):
            if k in fields:
                v = fields.get(k)
                raw = (v.get("value") if isinstance(v, dict) else v)
                norme = normalize_engine(raw)
                if norme:
                    if isinstance(v, dict):
                        fields[k]["value"] = norme
                    else:
                        fields[k] = {"value": norme, "confidence": 1.0}
                    try:
                        logger.debug("Normalized field", extra={"key": k, "raw": raw, "normalized": norme})
                    except Exception:
                        pass
        # Expiry dates (SIM/STNK/KIR)
        for k in ("expiry_date", "masa_berlaku"):
            if k in fields:
                v = fields.get(k)
                raw = (v.get("value") if isinstance(v, dict) else v)
                norme = normalize_expiry_date(raw)
                if norme:
                    if isinstance(v, dict):
                        fields[k]["value"] = norme
                    else:
                        fields[k] = {"value": norme, "confidence": 1.0}
                    try:
                        logger.debug("Normalized field", extra={"key": k, "raw": raw, "normalized": norme})
                    except Exception:
                        pass
        # RT/RW (KTP)
        for k in ("rt_rw", "rt", "rw"):
            if k in fields:
                v = fields.get(k)
                raw = (v.get("value") if isinstance(v, dict) else v)
                normr = normalize_rt_rw(raw)
                if normr:
                    # store normalized composite under rt_rw key; preserve existing keys
                    fields["rt_rw"] = {"value": normr, "confidence": 1.0}
                    try:
                        logger.debug("Normalized field", extra={"key": "rt_rw", "raw": raw, "normalized": normr})
                    except Exception:
                        pass
    except Exception:
        pass
    return fields

def _enforce_schema(doc_type: DocumentType, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Validate parsed fields against per-document Pydantic schemas.
    Returns a dict with is_valid, data (coerced), and errors.
    """
    values = _extract_values(fields or {})
    try:
        if doc_type == DocumentType.SIM:
            data = {k: values.get(k) for k in ("id_number", "name", "address", "expiry_date")}
            model = SIMDocument(**data)
            return {"is_valid": True, "data": model.model_dump(), "errors": []}
        if doc_type == DocumentType.STNK:
            data = {k: values.get(k) for k in ("nomor_polisi", "owner", "alamat", "nomor_rangka", "nomor_mesin")}
            model = STNKDocument(**data)
            return {"is_valid": True, "data": model.model_dump(), "errors": []}
        if doc_type == DocumentType.KIR:
            data = {k: values.get(k) for k in ("nomor_rangka", "nomor_mesin", "masa_berlaku", "tgl_uji")}
            model = KIRDocument(**data)
            return {"is_valid": True, "data": model.model_dump(), "errors": []}
        # For KTP and UNKNOWN, skip strict enforcement for now
        return {"is_valid": True, "data": values, "errors": []}
    except ValidationError as ve:
        return {"is_valid": False, "data": None, "errors": ve.errors()}


def _extract_values(fields: Dict[str, Any]) -> Dict[str, Any]:
    # Convert parser output to plain values by unwrapping {'value': x}
    out: Dict[str, Any] = {}
    for k, v in fields.items():
        if isinstance(v, dict) and "value" in v:
            out[k] = v.get("value")
        else:
            out[k] = v
    return out


def _safe_norm_str(x: Optional[str]) -> str:
    try:
        return (x or "").strip().upper()
    except Exception:
        return ""


def _name_similarity(a: Optional[str], b: Optional[str]) -> float:
    """Very lightweight token overlap similarity for names (0..1)."""
    aa = {t for t in _safe_norm_str(a).split() if t}
    bb = {t for t in _safe_norm_str(b).split() if t}
    if not aa or not bb:
        return 0.0
    inter = len(aa & bb)
    union = max(1, len(aa | bb))
    return inter / union


def _compute_verification_score(
    doc_type: DocumentType,
    extracted_values: Dict[str, Any],
    claimed: Dict[str, Optional[str]]
) -> Dict[str, Any]:
    """Compute a simple match score based on claimed identity vs extracted fields.
    Returns {score, decision, reasons, components}.
    """
    score_components: List[float] = []
    reasons: List[str] = []

    # KTP primarily: nik, name, dob
    if doc_type == DocumentType.KTP:
        nik_ex = _safe_norm_str(extracted_values.get("nik"))
        nik_cl = _safe_norm_str(claimed.get("nik"))
        if nik_cl:
            score_components.append(1.0 if nik_ex and nik_ex == nik_cl else 0.0)
            if nik_cl and nik_ex and nik_ex != nik_cl:
                reasons.append("nik_mismatch")

        nm_ex = _safe_norm_str(extracted_values.get("nama"))
        nm_cl = _safe_norm_str(claimed.get("name"))
        if nm_cl:
            sim = _name_similarity(nm_ex, nm_cl)
            score_components.append(sim)
            if sim < 0.5:
                reasons.append("name_low_similarity")

        dob_ex = _safe_norm_str(extracted_values.get("tanggal_lahir"))
        dob_cl = _safe_norm_str(claimed.get("dob"))
        if dob_cl:
            score_components.append(1.0 if dob_ex and dob_ex == dob_cl else 0.0)
            if dob_ex and dob_cl and dob_ex != dob_cl:
                reasons.append("dob_mismatch")

    # Fallback for other types: name only if available
    else:
        nm_ex = _safe_norm_str(extracted_values.get("nama") or extracted_values.get("name"))
        nm_cl = _safe_norm_str(claimed.get("name"))
        if nm_cl:
            sim = _name_similarity(nm_ex, nm_cl)
            score_components.append(sim)
            if sim < 0.5:
                reasons.append("name_low_similarity")

    # Aggregate score
    score = 0.0
    if score_components:
        score = sum(score_components) / len(score_components)
    return {
        "score": round(score, 3),
        "reasons": reasons,
        "components": score_components,
    }


def _compute_image_quality(image_bytes: bytes) -> Dict[str, Any]:
    """Compute simple image-quality signals from bytes.
    Returns a dict with keys: blur_score, brightness, is_blurry, is_too_dark
    """
    try:
        arr = np.frombuffer(image_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return {}
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        # Blur via variance of Laplacian
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        blur_score = float(lap.var())
        # Brightness as mean intensity normalized
        brightness = float(gray.mean()) / 255.0
        # Heuristic thresholds (slightly relaxed)
        is_blurry = blur_score < 80.0
        is_too_dark = brightness < 0.25
        # Color saturation separates photocopies/scans from photos of the
        # physical card: measured on real archive data, grayscale copies
        # sit at ~0-2 while every real photo is >=4 (mean HSV S channel)
        saturation = float(cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1].mean())
        return {
            "blur_score": round(blur_score, 3),
            "brightness": round(brightness, 3),
            "is_blurry": is_blurry,
            "is_too_dark": is_too_dark,
            "short_side": int(min(img.shape[:2])),
            "saturation": round(saturation, 3),
        }
    except Exception:
        return {}


def _build_validation(
    document_type: DocumentType,
    raw_text: List[str],
    parsed_fields: Optional[Dict[str, Any]] = None,
    image_quality: Optional[Dict[str, Any]] = None,
    schema_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Lightweight, non-breaking validation heuristics.
    Returns a dict with keys:
      - is_probably_valid: bool
      - reasons: List[str]
      - ocr_quality: float (0.0-1.0)
    """
    text = "\n".join((raw_text or [])).upper()
    reasons: List[str] = []

    # OCR quality proxy via ParserContext
    try:
        ctx = ParserContext(raw_lines=raw_text or [])
        quality = float(ctx.ocr_quality)
    except Exception:
        quality = 0.0

    # Basic content presence
    if not raw_text or len("".join(raw_text).strip()) < 10:
        reasons.append("very_low_text_content")

    # Document-specific keyword checks
    if document_type == DocumentType.KTP:
        ktp_hits = sum([
            int("NIK" in text),
            int("PROVINSI" in text),
            int("KABUPATEN" in text or "KOTA" in text),
            int("NAMA" in text),
        ])
        # NIK 16-digit pattern check (raw text)
        import re as _re
        has_nik_16 = bool(_re.search(r"\b\d{16}\b", text))
        # Also accept parsed field value as evidence
        parsed_nik = None
        try:
            if isinstance(parsed_fields, dict):
                v = parsed_fields.get("nik")
                parsed_nik = (v.get("value") if isinstance(v, dict) else v)
        except Exception:
            parsed_nik = None
        # Fallback to schema data
        if not parsed_nik and isinstance(schema_data, dict):
            try:
                v2 = schema_data.get("nik")
                parsed_nik = (v2.get("value") if isinstance(v2, dict) else v2)
            except Exception:
                pass
        if isinstance(parsed_nik, str) and _re.fullmatch(r"\d{16}", parsed_nik or ""):
            has_nik_16 = True
            # Count as a marker hit as well
            ktp_hits = max(ktp_hits, 2)

        if ktp_hits < 2 and not has_nik_16:
            reasons.append("missing_ktp_markers")
        if not has_nik_16:
            reasons.append("nik_pattern_not_found")
        # NIK self-consistency: region code + encoded DOB/gender vs extracted fields
        try:
            if isinstance(parsed_fields, dict):
                reasons.extend(nik_cross_check(parsed_fields))
        except Exception:
            pass
    elif document_type == DocumentType.SIM:
        # Accept multiple variants and English fallback
        variants = [
            "SURAT IZIN MENGEMUDI",
            " SIM ",  # padded to avoid matching parts of words
            "DRIVING LICENSE",
            "DRIVING LICEN",
        ]
        sim_hits = 0
        for v in variants:
            if v in f" {text} ":
                sim_hits += 1
        # If we have some reasonable OCR content or any parsed field, treat as present
        has_any_field = bool(parsed_fields) and any((parsed_fields or {}).values())
        if sim_hits < 1 and not has_any_field and len(raw_text or []) < 5:
            reasons.append("missing_sim_markers")
    elif document_type == DocumentType.STNK:
        # Accept common markers and synonyms
        variants = [
            " STNK ",
            "SURAT TANDA NOMOR KENDARAAN",
            " NOMOR RANGKA ",
            " NO. RANGKA ",
            " NOMOR MESIN ",
            " NO. MESIN ",
            " NOMOR POLISI ",
            " NO. POLISI ",
        ]
        stnk_hits = 0
        for v in variants:
            if v in f" {text} ":
                stnk_hits += 1
        has_any_field = bool(parsed_fields) and any((parsed_fields or {}).values())
        if stnk_hits < 1 and not has_any_field and len(raw_text or []) < 5:
            reasons.append("missing_stnk_markers")
    elif document_type == DocumentType.KIR:
        # Accept common markers and synonyms
        variants = [
            " KIR ",
            "KIR",
            " NOMOR RANGKA ",
            " NO. RANGKA ",
            " NOMOR MESIN ",
            " NO. MESIN ",
        ]
        kir_hits = 0
        for v in variants:
            if v in f" {text} ":
                kir_hits += 1
        has_any_field = bool(parsed_fields) and any((parsed_fields or {}).values())
        if kir_hits < 1 and not has_any_field and len(raw_text or []) < 5:
            reasons.append("missing_kir_markers")

    # Declared-vs-detected cross-check: the type often comes from a DB
    # column, an admin dropdown, or an upload slot — the photo may simply
    # be the wrong document. Report it; re-request is the caller's move.
    detected_type = None
    try:
        from app.utils.detection import detect_type_mismatch
        detected_type = detect_type_mismatch(document_type.value, raw_text)
        if detected_type:
            reasons.append("document_type_mismatch")
    except Exception:
        detected_type = None

    # Card-structure header check: a typed data-sheet replica carries the
    # field KEYWORDS but not the card's printed header. Advisory — a blurred
    # real card that loses its header lands in review, which is the designed
    # answer for that photo anyway. Matching is despaced (OCR glues words).
    _CARD_HEADERS = {
        DocumentType.KTP: ("PROVINSI", "KABUPATEN"),
        DocumentType.SIM: ("SURAT IZIN MENGEMUDI", "DRIVING LICENSE", "POLRI"),
        DocumentType.STNK: ("SURAT TANDA NOMOR KENDARAAN", "KEPOLISIAN",
                            "VEHICLE REGISTRATION", "NATIONAL POLICE"),
        DocumentType.KIR: ("UJI BERKALA", "PERIODIC INSPECTION", "KARTU UJI",
                           "PENGUJIAN KENDARAAN"),
    }
    headers = _CARD_HEADERS.get(document_type)
    if headers and raw_text:
        import re as _re2
        despaced = _re2.sub(r"[^A-Z]", "", text)
        if not any(h.replace(" ", "") in despaced for h in headers):
            reasons.append("missing_card_header")

    # Quality threshold hint
    if quality < 0.25:
        reasons.append("low_ocr_quality")

    # Image-quality advisory signals (if available)
    if isinstance(image_quality, dict):
        short_side = image_quality.get("short_side")
        if short_side is not None and short_side < int(getattr(settings, "MIN_IMAGE_SHORT_SIDE", 600)):
            reasons.append("resolution_too_low")
        saturation = image_quality.get("saturation")
        if saturation is not None and saturation < float(
                getattr(settings, "PHOTOCOPY_SATURATION_THRESHOLD", 3.0)):
            # advisory: readable data, but not evidence of holding the
            # original document — accept/review is the caller's POLICY
            reasons.append("grayscale_possible_photocopy")
        if image_quality.get("is_blurry"):
            # Suppress blur complaint if OCR quality is already decent
            if quality is not None and quality >= 0.75:
                pass
            else:
                reasons.append("blurry_image")
        if image_quality.get("is_too_dark"):
            reasons.append("too_dark")

    # Field richness check (if provided)
    if isinstance(parsed_fields, dict):
        num_fields = len([k for k, v in (parsed_fields or {}).items() if v is not None])
        if num_fields == 0:
            reasons.append("no_fields_extracted")
        # Specific hint: partial_nik present but nik missing
        try:
            has_partial = isinstance(parsed_fields.get("partial_nik"), dict) and parsed_fields.get("partial_nik", {}).get("value")
            nik_val = parsed_fields.get("nik")
            nik_missing = (nik_val is None) or (isinstance(nik_val, dict) and not nik_val.get("value"))
            if has_partial and nik_missing:
                reasons.append("nik_incomplete_digits")
        except Exception:
            pass

    is_probably_valid = len(reasons) == 0
    payload = {
        "is_probably_valid": is_probably_valid,
        "reasons": reasons,
        "ocr_quality": round(quality, 3),
    }
    if detected_type:
        payload["detected_type"] = detected_type
    if isinstance(image_quality, dict) and image_quality:
        payload["image_quality"] = image_quality
    return payload

class LinesOCRRequest(BaseModel):
    """Developer helper: directly parse provided OCR lines without running OCR."""
    document_type: DocumentType = Field(..., description="KTP, SIM, STNK, or KIR")
    lines: List[str] = Field(..., description="OCR lines to parse")
    debug: bool = Field(default=False, description="Enable debug behavior in parsers if supported")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_type": "SIM",
                "lines": [
                    "SURAT IZIN MENGEMUDI",
                    "Nama/Name : JOHN DOE"
                ]
            }
        }
    )

@router.post(
    "/ocr/lines",
    response_model=OCRResponse,
    summary="Parse provided OCR lines (no OCR step)",
    description=(
        "Developer utility to test the parsers by sending lines directly. "
        "Response data is normalized: data.fields.<key> is an object {value, confidence}."
    ),
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "Parsing successful",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "document_type": "SIM",
                        "processing_time": 0.42,
                        "timestamp": 1723780000.123,
                        "data": {
                            "raw_text": ["SURAT IZIN MENGEMUDI", "Nama : JOHN DOE"],
                            "fields": {
                                "nama": {"value": "JOHN DOE", "confidence": 0.95},
                                "gol_darah": {"value": "O", "confidence": 0.92}
                            }
                        }
                    }
                }
            }
        }
    }
)
async def process_document_lines(req: LinesOCRRequest) -> OCRResponse:
    start_time = time.time()
    # Auto-detect when requested
    eff_doc_type = req.document_type
    detection_meta = None
    if req.document_type == DocumentType.AUTO:
        detection_meta = detect_document_type_detailed(req.lines)
        eff_doc_type = detection_meta["doc_type"]
    parsed_payload = _dispatch_parse(eff_doc_type, req.lines)
    # Enrich with regex fallback if parsers missed key fields
    try:
        if isinstance(parsed_payload, dict):
            parsed_payload["fields"] = _regex_fallback_fields(eff_doc_type, req.lines, parsed_payload.get("fields") or {})
    except Exception:
        pass
    total_time = time.time() - start_time
    normalized = _normalize_parsed_payload(req.lines, parsed_payload)
    # Global conservative fixes
    normalized["fields"] = _postprocess_fields(normalized.get("fields", {}))
    # Schema enforcement (non-blocking here)
    normalized["schema"] = _enforce_schema(eff_doc_type, normalized.get("fields", {}))
    normalized["validation"] = _build_validation(eff_doc_type, req.lines, parsed_fields=normalized.get("fields"))
    meta = None
    if detection_meta is not None:
        meta = {
            "detection": {
                "detected_type": detection_meta["doc_type"].value,
                "scores": detection_meta["scores"],
                "matched_markers": detection_meta["matched_markers"],
                "confidence": detection_meta["confidence"],
            }
        }
    return OCRResponse(
        success=True,
        document_type=eff_doc_type.value,
        data=normalized,
        processing_time=total_time,
        timestamp=start_time,
        meta=meta,
    )

@router.post(
    "/ocr/file",
    response_model=OCRResponse,
    summary="Process document from file upload",
    description="""
    Process an uploaded document image using OCR.
    
    This endpoint accepts image files (JPEG, PNG, WebP) containing documents and returns
    the extracted text along with structured data based on the document type.
    
    ### Supported Document Types:
    - KTP (e-KTP): Indonesian ID card
    - SIM: Indonesian driver's license
    - STNK: Indonesian vehicle registration
    - KIR: Vehicle roadworthiness certificate
    
    ### Rate Limiting
    This endpoint is rate limited. Check response headers for rate limit information.
    """,
    response_description="OCR processing results including extracted text and metadata",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "OCR processing successful",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "document_type": "KTP",
                        "processing_time": 0.83,
                        "timestamp": 1723780000.321,
                        "data": {
                            "raw_text": ["..."],
                            "fields": {
                                "nik": {"value": "3175095801131001", "confidence": 0.99},
                                "nama": {"value": "JOHN DOE", "confidence": 0.97},
                                "alamat": {"value": "JL. MERDEKA NO.45", "confidence": 0.93}
                            },
                            "validation": {
                                "is_probably_valid": True,
                                "reasons": [],
                                "ocr_quality": 0.78
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "Invalid request or file format",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "invalid_file_format",
                            "message": "Unsupported file format. Please upload a JPEG, PNG, or WebP image."
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing API key",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "unauthorized",
                            "message": "Invalid or missing API key"
                        }
                    }
                }
            }
        },
        413: {
            "description": "File too large",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "file_too_large",
                            "message": "File size exceeds the maximum allowed limit of 5MB"
                        }
                    }
                }
            }
        },
        422: {
            "description": "Validation error (payload or, if enforce_validation=true, document validation)",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "validation_failed",
                            "message": "Document validation failed",
                            "reasons": ["missing_ktp_markers", "low_ocr_quality"],
                            "ocr_quality": 0.18
                        }
                    }
                }
            }
        },
        429: {
            "description": "Rate limit exceeded",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "rate_limit_exceeded",
                            "message": "Rate limit exceeded. Please try again in 60 seconds."
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "internal_server_error",
                            "message": "An unexpected error occurred while processing your request"
                        }
                    }
                }
            }
        },
    },
)
async def process_document_file(
    request: Request,
    response: Response,
    file: UploadFile = File(..., description="Image file to process"),
    document_type: DocumentType = Form(..., description="Type of document (AUTO, KTP, SIM, STNK, KIR)"),
    confidence_threshold: float = Form(0.7, description="Confidence threshold for OCR results (0.0-1.0)", ge=0.0, le=1.0),
    enforce_validation: bool = Query(
        default=False,
        description="If true, return 422 when document validation fails (advisory by default)"
    ),
    mode: Optional[str] = Query(
        default=None,
        description="OCR pipeline mode override: 'baseline' (default) or 'cascade'"
    )
) -> OCRResponse:
    """
    Process an uploaded document with OCR.
    
    This endpoint accepts image files for OCR processing and returns the extracted text
    along with structured data based on the document type.
    
    Args:
        request: The incoming request
        file: Uploaded image file (JPEG, PNG)
        document_type: Type of document (KTP, SIM, STNK, KIR)
        confidence_threshold: Minimum confidence score for OCR results (0.0-1.0)
        
    Returns:
        OCRResponse with extracted data and processing metadata
    """
    start_time = time.time()
    
    try:
        # Validate file upload
        is_valid, error = validate_file_upload(file)
        try:
            logger.info(
                "VAL2 validate_file_upload",
                extra={"is_valid": is_valid, "error": error}
            )
        except Exception:
            pass
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"[ROUTE-VAL] {error}"
            )
        
        # Validate document type (AUTO allowed)
        is_valid, error = validate_document_type(document_type.value)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )
        
        # Read the file content (PDFs are rendered to an image first)
        from app.utils.pdf_input import normalize_upload
        contents = normalize_upload(await file.read())
        # Enforce file size limit
        try:
            max_bytes = int(getattr(settings, 'MAX_UPLOAD_BYTES', 10 * 1024 * 1024))
        except Exception:
            max_bytes = 10 * 1024 * 1024
        if len(contents or b"") > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "error": {
                        "code": "file_too_large",
                        "message": f"File size exceeds the maximum allowed limit of {int(max_bytes/1024/1024)}MB",
                    }
                },
            )

        # Decode image; reject bytes that are not a decodable image.
        # (OCR on undecodable bytes always yields nothing, so failing fast
        # with 400 is strictly more honest than a 200 with empty fields.)
        try:
            arr = np.frombuffer(contents, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        except Exception:
            img = None
        if img is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": "invalid_image",
                        "message": "Unable to decode image bytes. Please upload a valid JPEG, PNG, or WebP image.",
                    }
                },
            )
        # Enforce max image dimensions (<= 5000 x 5000)
        h, w = img.shape[:2]
        if h > 5000 or w > 5000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": "invalid_image_dimensions",
                        "message": "Image dimensions exceed the maximum allowed size of 5000x5000 pixels",
                        "height": h,
                        "width": w,
                    }
                },
            )
        img_quality = _compute_image_quality(contents)
        # Determine selected pipeline mode early (query param > config)
        try:
            default_mode = str(getattr(settings, "OCR_PIPELINE_MODE", "baseline")).lower().strip()
        except Exception:
            default_mode = "baseline"
        sel_mode = (mode or default_mode or "baseline").lower().strip()
        if sel_mode not in {"baseline", "cascade"}:
            sel_mode = "baseline"
        
        # Every value the validators drop gets recorded from here on, so the
        # response can show what was read and refused — not just what shipped.
        journal_begin()

        # Extract text via selected pipeline.
        # OCR is CPU-bound and synchronous; run it in a worker thread so the
        # event loop keeps serving other requests.
        ocr_start = time.time()
        doc_hint = document_type.value if document_type != DocumentType.AUTO else None
        if sel_mode == "cascade" and 'img' in locals() and img is not None:
            try:
                cascade = CascadePipeline()
                pipe_res = await run_in_threadpool(cascade.run, img, doc_type_hint=doc_hint)
                ocr_results = pipe_res.get("lines", [])
                ocr_items = []
                pipeline_meta = pipe_res.get("meta", {})
            except Exception:
                # Safety fallback to baseline OCR if cascade fails
                ocr_results, ocr_items = await run_in_threadpool(
                    lambda: extract_text_from_image(contents, doc_type=doc_hint, return_items=True))
                pipeline_meta = {"error": "cascade_failed_fallback_baseline"}
        else:
            ocr_results, ocr_items = await run_in_threadpool(
                lambda: extract_text_from_image(contents, doc_type=doc_hint, return_items=True))
            pipeline_meta = {}
        ocr_time = time.time() - ocr_start

        # Auto-detect when requested
        eff_doc_type = document_type
        detection_meta = None
        if document_type == DocumentType.AUTO:
            detection_meta = detect_document_type_detailed(ocr_results)
            eff_doc_type = detection_meta["doc_type"]

            # Wallet photos: two documents in one frame make detection
            # ambiguous (two types score strongly). Split by text-box
            # geometry and parse each document separately.
            strong_types = [t for t, s in detection_meta["scores"].items() if s >= 3.0]
            if len(strong_types) >= 2:
                from app.parser.multi_doc import try_split_documents
                split = await run_in_threadpool(try_split_documents, contents, hint_types=strong_types)
                if split:
                    documents = []
                    for entry in split:
                        sub_type = entry["document_type"]
                        sub_payload = _dispatch_parse(sub_type, entry["lines"])
                        sub_fields = sub_payload.get("fields") or {}
                        try:
                            sub_fields = _regex_fallback_fields(sub_type, entry["lines"], sub_fields)
                        except Exception:
                            pass
                        # A split document deserves the same treatment as a
                        # single one: geometry pairing, then the trained
                        # detector on the sub-document's own crop. Without
                        # these the MULTI path returned empty fields for every
                        # wallet photo.
                        sub_fields = await _enrich_fields(
                            sub_type,
                            entry["lines"],
                            entry.get("items") or [],
                            sub_fields,
                            image_bytes=_sub_image(contents, entry.get("bbox")),
                            detection_confidence=(entry.get("detection") or {}).get("confidence", 0.0),
                        )
                        sub_norm = _normalize_parsed_payload(entry["lines"], {"fields": sub_fields})
                        sub_norm["fields"] = _postprocess_fields(sub_norm.get("fields", {}))
                        sub_norm["fields"] = strip_label_residue(sub_norm["fields"])
                        sub_norm["fields"] = validate_fields(sub_type.value, sub_norm["fields"])
                        sub_norm["fields"] = derive_aliases(sub_type.value, sub_norm["fields"])
                        documents.append({
                            "document_type": sub_type.value,
                            "detection": {
                                "scores": entry["detection"]["scores"],
                                "confidence": entry["detection"]["confidence"],
                            },
                            "data": sub_norm,
                        })
                    total_time = time.time() - start_time
                    # local import mirrors the function's existing pattern
                    # (a later in-function import makes the name local)
                    from app.monitoring.metrics import record_ocr_metrics as _record
                    _record(document_type="MULTI", processing_time=total_time, success=True)
                    return JSONResponse(content=jsonable_encoder({
                        "success": True,
                        "document_type": "MULTI",
                        "documents": documents,
                        "processing_time": total_time,
                        "timestamp": start_time,
                        "meta": {"detection": {
                            "detected_type": "MULTI",
                            "scores": detection_meta["scores"],
                            "documents_found": [d["document_type"] for d in documents],
                        }},
                    }))

        # Parse the extracted text based on effective document type
        parse_start = time.time()
        parsed_payload = _dispatch_parse(eff_doc_type, ocr_results)
        # Enrich with regex fallback if parsers missed key fields
        try:
            if isinstance(parsed_payload, dict):
                parsed_payload["fields"] = _regex_fallback_fields(eff_doc_type, ocr_results, parsed_payload.get("fields") or {})
        except Exception:
            pass
        # Geometry pairing, SIM expiry recovery, trained detector, spec fields.
        # Shared with the MULTI path so the two cannot drift apart.
        if isinstance(parsed_payload, dict):
            parsed_payload["fields"] = await _enrich_fields(
                eff_doc_type,
                ocr_results,
                ocr_items or [],
                parsed_payload.get("fields") or {},
                image_bytes=contents,
                detection_confidence=(detection_meta or {}).get("confidence", 0.0),
            )
        parse_time = time.time() - parse_start
        
        # Calculate total processing time
        total_time = time.time() - start_time
        
        # Record metrics using the record_ocr_metrics function
        from app.monitoring.metrics import record_ocr_metrics
        record_ocr_metrics(
            document_type=eff_doc_type.value,
            processing_time=total_time,
            success=True,
            pipeline_mode=sel_mode,
            used_fallback=bool((pipeline_meta or {}).get("used_fallback", False)),
        )
        
        # Prepare response
        normalized = _normalize_parsed_payload(ocr_results, parsed_payload)
        # Global conservative fixes
        normalized["fields"] = _postprocess_fields(normalized.get("fields", {}))
        # A printed label is never a value. Drop it rather than ship it.
        normalized["fields"] = strip_label_residue(normalized.get("fields", {}))
        # Vocabulary, cross-field and format checks. A fabricated national ID
        # number, a plate whose region code does not exist, or a sex that is not
        # a sex are all worse than a missing value: nothing reviews a wrong one.
        normalized["fields"] = validate_fields(eff_doc_type.value, normalized["fields"])
        # Where each value sits on the page — the customer's spec asks for every
        # field as a numbered BOX on the photo, and the geometry was being thrown
        # away. This must run AFTER normalization: the document parsers emit their
        # own field objects, and only normalization flattens every stage's output
        # into the plain dicts a box can be attached to.
        try:
            if ocr_items:
                from app.parser.locate import attach_bboxes, image_size_of
                normalized["fields"] = attach_bboxes(
                    normalized["fields"], ocr_items, image_size_of(contents))
        except Exception:
            logger.exception("bbox attachment failed")
        # Aliases are a VIEW of the canonical field and must be derived last,
        # once every stage has had its say.
        normalized["fields"] = derive_aliases(eff_doc_type.value, normalized.get("fields", {}))
        # Schema enforcement
        normalized["schema"] = _enforce_schema(eff_doc_type, normalized.get("fields", {}))
        normalized["validation"] = _build_validation(
            eff_doc_type,
            ocr_results,
            parsed_fields=normalized.get("fields"),
            image_quality=img_quality,
            schema_data=(normalized.get("schema") or {}).get("data"),
        )
        # QR payloads: modern KIR (BLU-e) and new SIMs carry QR codes with
        # authoritative data — when decodable, callers should prefer these
        # over OCR text
        try:
            from app.utils.qr_reader import decode_qr_codes
            qr = await run_in_threadpool(decode_qr_codes, contents)
            if qr:
                normalized["qr_codes"] = qr
        except Exception:
            pass
        # Build meta for observability
        try:
            meta = {
                "pipeline_mode": sel_mode,
                "used_fallback": False,
                "low_conf_threshold": float(getattr(settings, "LOW_CONF_THRESHOLD", 0.70)),
                "max_fallbacks": int(getattr(settings, "MAX_FALLBACKS", 1)),
                "min_fields_for_pass": int(getattr(settings, "MIN_FIELDS_FOR_PASS", 3)),
            }
            if pipeline_meta:
                meta["pipeline"] = pipeline_meta
        except Exception:
            meta = {"pipeline_mode": sel_mode, "used_fallback": False}
        if detection_meta is not None:
            meta["detection"] = {
                "detected_type": detection_meta["doc_type"].value,
                "scores": detection_meta["scores"],
                "matched_markers": detection_meta["matched_markers"],
                "confidence": detection_meta["confidence"],
            }
        # Temporary debug logging for failed SIM/STNK/KIR cases
        try:
            if eff_doc_type in {DocumentType.SIM, DocumentType.STNK, DocumentType.KIR}:
                val = normalized.get("validation") or {}
                sch = normalized.get("schema") or {}
                if (not val.get("is_probably_valid", True)) or (not sch.get("is_valid", True)):
                    # PII redaction: log which fields were present and the
                    # failure reasons — never the extracted values or raw
                    # OCR text (these contain NIK/names of real people)
                    logger.warning(
                        "OCR debug: validation/schema failed",
                        extra={
                            "document_type": eff_doc_type.value,
                            "reasons": val.get("reasons"),
                            "ocr_quality": val.get("ocr_quality"),
                            "schema_errors": sch.get("errors"),
                            "lines_read": len(ocr_results),
                            "fields_present": sorted((normalized.get("fields") or {}).keys()),
                        },
                    )
        except Exception:
            pass
        if enforce_validation and (not normalized["validation"]["is_probably_valid"] or not normalized["schema"]["is_valid"]):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "validation_failed",
                        "message": "Document validation failed",
                        "reasons": normalized["validation"]["reasons"],
                        "schema_errors": normalized["schema"].get("errors"),
                        "ocr_quality": normalized["validation"]["ocr_quality"],
                    }
                }
            )
        # How the answer was produced — every stage, in the open. The console
        # renders this; it is also the honest way to answer "how does the OCR
        # work?" without a slide that says "AI magic".
        try:
            img_size = None
            try:
                from app.parser.locate import image_size_of
                img_size = image_size_of(contents)
            except Exception:
                pass
            by_stage: Dict[str, int] = {}
            for rec in (normalized.get("fields") or {}).values():
                if not isinstance(rec, dict):
                    continue
                m = ((rec.get("provenance") or {}).get("method")
                     or ("alias" if (rec.get("provenance") or {}).get("alias_of")
                         else "rule_extractor"))
                by_stage[m] = by_stage.get(m, 0) + 1
            w, h = img_size or (0, 0)
            meta["trace"] = {
                "image": {"width": w, "height": h},
                "ocr": {
                    "lines": len(ocr_results or []),
                    "seconds": round(ocr_time, 1),
                    # what the OCR actually SAW: every text line and where it sits
                    "items": [
                        {
                            "text": it.get("text"),
                            "conf": round(float(it.get("conf") or 0), 3),
                            "norm": ({
                                "x0": round(max(0.0, min(1.0, float(it["x0"]) / w)), 4),
                                "y0": round(max(0.0, min(1.0, (float(it["cy"]) - float(it.get("h") or 0) / 2) / h)), 4),
                                "x1": round(max(0.0, min(1.0, float(it["x1"]) / w)), 4),
                                "y1": round(max(0.0, min(1.0, (float(it["cy"]) + float(it.get("h") or 0) / 2) / h)), 4),
                            } if (w and h) else None),
                        }
                        for it in (ocr_items or [])
                    ],
                },
                "fields_by_stage": by_stage,
                # the values we READ and REFUSED to ship
                "dropped": journal_entries(),
            }
        except Exception:
            logger.exception("trace assembly failed")

        response_data = OCRResponse(
            success=True,
            document_type=eff_doc_type.value,
            data=normalized,
            processing_time=total_time,
            timestamp=start_time,
            meta=meta,
        )
        # Set processing time header for observability
        try:
            response.headers["X-Processing-Time"] = f"{total_time:.3f}"
            response.headers["X-Pipeline-Mode"] = sel_mode
        except Exception:
            pass
        
        # Log successful processing
        logger.info(
            "Document processed successfully",
            extra={
                "document_type": eff_doc_type.value,
                "file_size": len(contents),
                "processing_time": total_time,
                "ocr_time": ocr_time,
                "parse_time": parse_time,
                "pipeline_mode": sel_mode,
                "used_fallback": False,
                "status": "success"
            }
        )
        
        return response_data
        
    except HTTPException:
        # Re-raise HTTP exceptions with their original status codes
        raise
        
    except Exception as e:
        # Log the error
        error_detail = f"Error processing document: {str(e)}"
        logger.error(
            error_detail,
            extra={
                "document_type": (eff_doc_type.value if 'eff_doc_type' in locals() else (document_type.value if 'document_type' in locals() else 'unknown')),
                "error": str(e),
                "traceback": traceback.format_exc(),
                "status": "error"
            }
        )
        
        # Record error metrics using the correct metrics tracking
        from app.monitoring.metrics import record_ocr_metrics
        record_ocr_metrics(
            document_type=(eff_doc_type.value if 'eff_doc_type' in locals() else (document_type.value if 'document_type' in locals() else 'unknown')),
            processing_time=time.time() - start_time,
            success=False,
            error=str(e)
        )
        
        # Return error response
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "processing_error",
                    "message": "An error occurred while processing the document",
                    "details": str(e)
                }
            }
        )
        
    finally:
        # Ensure file is closed
        if 'file' in locals():
            await file.close()


@router.post(
    "/ocr/verify",
    response_model=OCRResponse,
    summary="Verify uploaded document against claimed identity",
    description=(
        "Uploads an image and compares extracted fields to claimed identity attributes (e.g., NIK, name, DOB). "
        "Returns OCR data plus a verification block with score and decision."
    ),
    status_code=status.HTTP_200_OK,
)
async def verify_document_file(
    request: Request,
    file: UploadFile = File(..., description="Image file to process"),
    document_type: DocumentType = Form(..., description="Type of document (AUTO, KTP, SIM, STNK, KIR)"),
    claimed_nik: Optional[str] = Form(None, description="Claimed NIK (for KTP)"),
    claimed_name: Optional[str] = Form(None, description="Claimed full name"),
    claimed_dob: Optional[str] = Form(None, description="Claimed date of birth in YYYY-MM-DD"),
    score_threshold: float = Form(0.7, description="Decision threshold for match (0.0-1.0)", ge=0.0, le=1.0),
    enforce_validation: bool = Query(False, description="If true, return 422 when document validation fails")
) -> OCRResponse:
    start_time = time.time()
    try:
        is_valid, error = validate_file_upload(file)
        if not is_valid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"[ROUTE-VAL] {error}")

        is_valid, error = validate_document_type(document_type.value)
        if not is_valid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)

        contents = await file.read()
        img_quality = _compute_image_quality(contents)

        doc_hint = document_type.value if document_type != DocumentType.AUTO else None
        ocr_results = await run_in_threadpool(extract_text_from_image, contents, doc_type=doc_hint)

        eff_doc_type = document_type
        if document_type == DocumentType.AUTO:
            eff_doc_type = detect_document_type(ocr_results)

        parsed_payload = _dispatch_parse(eff_doc_type, ocr_results)
        total_time = time.time() - start_time

        normalized = _normalize_parsed_payload(ocr_results, parsed_payload)
        normalized["fields"] = _postprocess_fields(normalized.get("fields", {}))
        normalized["schema"] = _enforce_schema(eff_doc_type, normalized.get("fields", {}))
        normalized["validation"] = _build_validation(
            eff_doc_type, ocr_results, parsed_fields=normalized.get("fields"), image_quality=img_quality
        )
        if enforce_validation and (not normalized["validation"]["is_probably_valid"] or not normalized["schema"]["is_valid"]):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": {
                        "code": "validation_failed",
                        "message": "Document validation failed",
                        "reasons": normalized["validation"]["reasons"],
                        "schema_errors": normalized["schema"].get("errors"),
                        "ocr_quality": normalized["validation"]["ocr_quality"],
                    }
                }
            )

        # Verification scoring
        extracted_values = _extract_values(normalized.get("fields", {}))
        claims = {"nik": claimed_nik, "name": claimed_name, "dob": claimed_dob}
        verify = _compute_verification_score(eff_doc_type, extracted_values, claims)
        decision = "match" if verify["score"] >= float(score_threshold) else "no_match"
        normalized["verification"] = {
            "score": verify["score"],
            "threshold": score_threshold,
            "decision": decision,
            "reasons": verify["reasons"],
        }

        # Record metrics
        record_ocr_metrics(document_type=eff_doc_type.value, processing_time=total_time, success=True)

        return OCRResponse(
            success=True,
            document_type=eff_doc_type.value,
            data=normalized,
            processing_time=total_time,
            timestamp=start_time,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Verification error", extra={"error": str(e)})
        record_ocr_metrics(
            document_type=(document_type.value if 'document_type' in locals() else 'unknown'),
            processing_time=time.time() - start_time,
            success=False,
            error=str(e)
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail={"error": {"code": "verification_error", "message": str(e)}})
    finally:
        if 'file' in locals():
            await file.close()

@router.get("/health")
async def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for monitoring.
    
    Returns:
        Dict with service status information
    """
    return {
        "status": "healthy",
        "timestamp": time.time(),
        "service": "ocr-api",
        "version": "1.0.0"
    }

@router.post(
    "/ocr/url",
    response_model=OCRResponse,
    summary="Process document from URL",
    description="""
    Process a document image from a URL using OCR.
    
    This endpoint accepts a publicly accessible URL to an image file (JPEG, PNG, WebP) 
    containing a document and returns the extracted text along with structured data 
    based on the document type.
    
    ### Supported Document Types:
    - KTP (e-KTP): Indonesian ID card
    - SIM: Indonesian driver's license
    - STNK: Indonesian vehicle registration
    - KIR: Vehicle roadworthiness certificate
    
    ### Rate Limiting
    This endpoint is rate limited. Check response headers for rate limit information.
    
    ### Security
    - Only HTTP/HTTPS URLs are allowed
    - Maximum file size: 10MB
    - Image dimensions must not exceed 5000x5000 pixels
    """,
    response_description="OCR processing results including extracted text and metadata",
    status_code=status.HTTP_200_OK,
    responses={
        200: {
            "description": "OCR processing successful",
            "content": {
                "application/json": {
                    "example": {
                        "success": True,
                        "document_type": "KTP",
                        "processing_time": 0.71,
                        "timestamp": 1723780001.111,
                        "data": {
                            "raw_text": ["..."],
                            "fields": {
                                "nik": {"value": "3175095801131001", "confidence": 0.99},
                                "nama": {"value": "JOHN DOE", "confidence": 0.97},
                                "alamat": {"value": "JL. MERDEKA NO.45", "confidence": 0.93}
                            },
                            "validation": {
                                "is_probably_valid": True,
                                "reasons": [],
                                "ocr_quality": 0.8
                            }
                        }
                    }
                }
            }
        },
        400: {
            "description": "Invalid URL or image format",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "invalid_url",
                            "message": "Invalid or inaccessible image URL"
                        }
                    }
                }
            }
        },
        401: {
            "description": "Unauthorized - Invalid or missing API key",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "unauthorized",
                            "message": "Invalid or missing API key"
                        }
                    }
                }
            }
        },
        404: {
            "description": "Image not found at URL",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "image_not_found",
                            "message": "The specified image could not be found at the provided URL"
                        }
                    }
                }
            }
        },
        413: {
            "description": "File too large",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "file_too_large",
                            "message": "File size exceeds the maximum allowed limit of 10MB"
                        }
                    }
                }
            }
        },
        422: {
            "description": "Validation error (payload or, if enforce_validation=true, document validation)",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "validation_failed",
                            "message": "Document validation failed",
                            "reasons": ["missing_ktp_markers"],
                            "ocr_quality": 0.2
                        }
                    }
                }
            }
        },
        429: {
            "description": "Rate limit exceeded",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "rate_limit_exceeded",
                            "message": "Rate limit exceeded. Please try again in 60 seconds."
                        }
                    }
                }
            }
        },
        500: {
            "description": "Internal server error",
            "content": {
                "application/json": {
                    "example": {
                        "error": {
                            "code": "internal_server_error",
                            "message": "An unexpected error occurred while processing your request"
                        }
                    }
                }
            }
        },
    },
)
async def process_document_url(
    request: Request,
    response: Response,
    ocr_request: URLOcrRequest,
    enforce_validation: bool = Query(
        default=False,
        description="If true, return 422 when document validation fails (advisory by default)"
    ),
    mode: Optional[str] = Query(
        default=None,
        description="OCR pipeline mode override: 'baseline' (default) or 'cascade'"
    ),
) -> OCRResponse:
    """Process a document from a URL with OCR.
    
    This endpoint accepts a URL to an image for OCR processing and returns the extracted text
    along with structured data based on the document type.
    
    Args:
        request: The incoming request
        ocr_request: URL OCR request containing the image URL and processing options
        
    Returns:
        OCRResponse with extracted data and processing metadata
    """
    start_time = time.time()
    
    try:
        # Validate document type
        is_valid, error = validate_document_type(ocr_request.document_type.value)
        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error
            )
        
        # Download the image from URL
        try:
            import httpx
            from io import BytesIO
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                dl_resp = await client.get(str(ocr_request.image_url))
                dl_resp.raise_for_status()
                
                # Check content type
                content_type = dl_resp.headers.get('content-type', '').lower()
                if not any(x in content_type for x in ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail={
                            "error": {
                                "code": "invalid_image_type",
                                "message": "Unsupported image type. Please provide a JPEG, PNG, or WebP image."
                            }
                        }
                    )
                
                # Check file size (max 10MB)
                content_length = int(dl_resp.headers.get('content-length', 0))
                if content_length > 10 * 1024 * 1024:  # 10MB
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail={
                            "error": {
                                "code": "file_too_large",
                                "message": "File size exceeds the maximum allowed limit of 10MB"
                            }
                        }
                    )
                
                image_data = BytesIO(dl_resp.content)
                
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail={
                        "error": {
                            "code": "image_not_found",
                            "message": "The specified image could not be found at the provided URL"
                        }
                    }
                )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": "download_failed",
                        "message": f"Failed to download image from URL: {str(e)}"
                    }
                }
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": {
                        "code": "invalid_url",
                        "message": f"Invalid or inaccessible image URL: {str(e)}"
                    }
                }
            )
        
        # Process the downloaded image
        try:
            # Extract text using selected pipeline
            ocr_start = time.time()
            img_bytes = image_data.getvalue()
            doc_hint = ocr_request.document_type.value if ocr_request.document_type != DocumentType.AUTO else None
            # Create np.ndarray for cascade if needed
            arr = np.frombuffer(img_bytes, dtype=np.uint8)
            url_img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            # Determine selected pipeline mode early (query param > config)
            try:
                default_mode = str(getattr(settings, "OCR_PIPELINE_MODE", "baseline")).lower().strip()
            except Exception:
                default_mode = "baseline"
            sel_mode = (mode or default_mode or "baseline").lower().strip()
            if sel_mode not in {"baseline", "cascade"}:
                sel_mode = "baseline"
            if sel_mode == "cascade" and url_img is not None:
                try:
                    cascade = CascadePipeline()
                    pipe_res = await run_in_threadpool(cascade.run, url_img, doc_type_hint=doc_hint)
                    ocr_results = pipe_res.get("lines", [])
                    pipeline_meta = pipe_res.get("meta", {})
                except Exception:
                    # Fallback to baseline OCR
                    ocr_results = await run_in_threadpool(extract_text_from_image, img_bytes, doc_type=doc_hint)
                    pipeline_meta = {"error": "cascade_failed_fallback_baseline"}
            else:
                ocr_results = await run_in_threadpool(extract_text_from_image, img_bytes, doc_type=doc_hint)
                pipeline_meta = {}
            ocr_time = time.time() - ocr_start

            # Determine effective document type (auto-detect if requested)
            eff_doc_type = ocr_request.document_type
            detection_meta = None
            if ocr_request.document_type == DocumentType.AUTO:
                detection_meta = detect_document_type_detailed(ocr_results)
                eff_doc_type = detection_meta["doc_type"]

            # Parse the extracted text based on effective document type
            parse_start = time.time()
            parsed_payload = _dispatch_parse(eff_doc_type, ocr_results)
            # Enrich with regex fallback if parsers missed key fields
            try:
                if isinstance(parsed_payload, dict):
                    parsed_payload["fields"] = _regex_fallback_fields(eff_doc_type, ocr_results, parsed_payload.get("fields") or {})
            except Exception:
                pass
            parse_time = time.time() - parse_start

            # Calculate total processing time
            total_time = time.time() - start_time

            # Record metrics using the record_ocr_metrics function
            from app.monitoring.metrics import record_ocr_metrics
            record_ocr_metrics(
                document_type=eff_doc_type.value,
                processing_time=total_time,
                success=True,
                pipeline_mode=sel_mode,
                used_fallback=bool((pipeline_meta or {}).get("used_fallback", False)),
            )

            # Prepare response
            normalized = _normalize_parsed_payload(ocr_results, parsed_payload)
            # Global conservative fixes
            normalized["fields"] = _postprocess_fields(normalized.get("fields", {}))
            # Schema enforcement
            normalized["schema"] = _enforce_schema(eff_doc_type, normalized.get("fields", {}))
            normalized["validation"] = _build_validation(eff_doc_type, ocr_results, parsed_fields=normalized.get("fields"))

            # Enforce validation when requested (parity with /ocr/file)
            if enforce_validation and (not normalized["validation"]["is_probably_valid"] or not normalized["schema"]["is_valid"]):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail={
                        "error": {
                            "code": "validation_failed",
                            "message": "Document validation failed",
                            "reasons": normalized["validation"]["reasons"],
                            "schema_errors": normalized["schema"].get("errors"),
                            "ocr_quality": normalized["validation"]["ocr_quality"],
                        }
                    }
                )

            # Build meta for observability
            try:
                meta = {
                    "pipeline_mode": sel_mode,
                    "used_fallback": False,
                    "low_conf_threshold": float(getattr(settings, "LOW_CONF_THRESHOLD", 0.70)),
                    "max_fallbacks": int(getattr(settings, "MAX_FALLBACKS", 1)),
                    "min_fields_for_pass": int(getattr(settings, "MIN_FIELDS_FOR_PASS", 3)),
                }
                if pipeline_meta:
                    meta["pipeline"] = pipeline_meta
            except Exception:
                meta = {"pipeline_mode": sel_mode, "used_fallback": False}
            if detection_meta is not None:
                meta["detection"] = {
                    "detected_type": detection_meta["doc_type"].value,
                    "scores": detection_meta["scores"],
                    "matched_markers": detection_meta["matched_markers"],
                    "confidence": detection_meta["confidence"],
                }

            # Log successful processing
            logger.info(
                "Document URL processed successfully",
                extra={
                    "document_type": eff_doc_type.value,
                    "processing_time": total_time,
                    "ocr_time": ocr_time,
                    "parse_time": parse_time,
                    "status": "success",
                    "pipeline_mode": sel_mode,
                }
            )

            # Set headers
            try:
                response.headers["X-Processing-Time"] = f"{total_time:.3f}"
                response.headers["X-Pipeline-Mode"] = sel_mode
            except Exception:
                pass

            return OCRResponse(
                success=True,
                document_type=eff_doc_type.value,
                data=normalized,
                processing_time=total_time,
                timestamp=start_time,
                meta=meta,
            )
            
        except Exception as e:
            # Log the error
            logger.error(
                f"Error processing downloaded image: {str(e)}",
                extra={
                    "document_type": ocr_request.document_type.value,
                    "url": str(ocr_request.image_url),
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                    "status": "error",
                    "pipeline_mode": (mode or getattr(settings, "OCR_PIPELINE_MODE", "baseline")),
                }
            )
            
            # Record error metrics
            metrics.processing_errors.labels(
                document_type=ocr_request.document_type.value,
                error_type=e.__class__.__name__
            ).inc()
            
            # Return error response
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": {
                        "code": "processing_error",
                        "message": "An error occurred while processing the downloaded image",
                        "details": str(e)
                    }
                }
            )
        
    except HTTPException:
        # Re-raise HTTP exceptions with their original status codes
        raise
        
    except Exception as e:
        # Log the error
        error_detail = f"Error processing document from URL: {str(e)}"
        logger.error(
            error_detail,
            extra={
                "document_type": ocr_request.document_type.value,
                "url": str(ocr_request.image_url),
                "error": str(e),
                "traceback": traceback.format_exc(),
                "status": "error"
            }
        )
        
        # Record error metrics
        metrics.processing_errors.labels(
            document_type=ocr_request.document_type.value,
            error_type=e.__class__.__name__
        ).inc()
        
        # Return error response
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "error": {
                    "code": "processing_error",
                    "message": "An error occurred while processing the document from URL",
                    "details": str(e)
                }
            }
        )