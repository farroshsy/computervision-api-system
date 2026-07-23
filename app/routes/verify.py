"""Verification endpoints: single document and whole-trip checks.

These wrap OCR + parsing + the verification engine
(app/services/verification.py) into the two calls a dispatch system
actually makes:

- POST /api/v1/verify/document — one image + claims -> match/no_match/needs_review
- POST /api/v1/verify/trip     — SIM + STNK + KIR images + claims -> GO/NO_GO/REVIEW
"""
import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.services.paddle_ocr import extract_text_from_image
from app.services.verification import aggregate_trip, verify_document
from app.routes.ocr import _dispatch_parse, _extract_values, _regex_fallback_fields
from app.schemas.request_models import DocumentType
from app.utils.id_reference import fuzzy_correct_fields
from app.utils.validation import validate_file_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/verify", tags=["verify"])


def _parse_required_classes(raw: Optional[str]) -> Optional[List[str]]:
    """Accept JSON array or comma-separated string."""
    if not raw:
        return None
    try:
        v = json.loads(raw)
        if isinstance(v, list):
            return [str(x) for x in v]
    except json.JSONDecodeError:
        pass
    return [p.strip() for p in raw.split(",") if p.strip()]


async def _ocr_and_verify(
    contents: bytes,
    doc_type: DocumentType,
    claims: Dict[str, Optional[str]],
    required_classes: Optional[List[str]],
) -> Dict:
    lines, items = await run_in_threadpool(
        lambda: extract_text_from_image(contents, doc_type=doc_type.value, return_items=True))
    payload = _dispatch_parse(doc_type, lines)
    fields = payload.get("fields") or {}
    try:
        fields = _regex_fallback_fields(doc_type, lines, fields)
    except Exception:
        pass
    try:
        if doc_type.value in ("KIR", "STNK", "KTP", "SIM") and items:
            from app.parser.spatial_pairing import pair_fields_spatially
            fields = pair_fields_spatially(doc_type.value, items, fields)
    except Exception:
        pass
    try:
        if doc_type.value in ("STNK", "KTP"):
            from app.parser.field_detector import enrich_with_detector
            fields = await run_in_threadpool(enrich_with_detector, doc_type.value, contents, fields)
    except Exception:
        pass
    try:
        if doc_type.value == "SIM" and items:
            from app.parser.sim_expiry_zone import recover_sim_expiry
            fields = await run_in_threadpool(recover_sim_expiry, contents, items, fields)
    except Exception:
        pass
    fields = fuzzy_correct_fields(fields)
    values = _extract_values(fields)
    result = verify_document(doc_type.value, values, claims, required_classes=required_classes)
    result["extracted"] = {c["field"]: c["extracted"] for c in result["checks"]}
    result["lines_read"] = len(lines)
    # Wrong evidence must never produce a match OR a no_match: a KIR in
    # the STNK slot can still parse a plate (false match) and its expiry
    # reasons are meaningless (false block). Route to review + say what
    # the photo actually is so the flow can re-request the right one.
    try:
        from app.utils.detection import detect_type_mismatch
        detected = detect_type_mismatch(doc_type.value, lines)
        if detected:
            result["decision"] = "needs_review"
            result["reasons"] = list(result.get("reasons") or []) + ["wrong_document_type"]
            result["detected_type"] = detected
    except Exception:
        pass
    return result


@router.post("/document", summary="Verify one document against claimed values")
async def verify_single_document(
    file: UploadFile = File(...),
    document_type: DocumentType = Form(..., description="KTP, SIM, STNK, or KIR"),
    claimed_nik: Optional[str] = Form(None),
    claimed_name: Optional[str] = Form(None),
    claimed_dob: Optional[str] = Form(None, description="YYYY-MM-DD"),
    claimed_sim_number: Optional[str] = Form(None),
    claimed_plate: Optional[str] = Form(None),
    claimed_nomor_rangka: Optional[str] = Form(None),
    required_classes: Optional[str] = Form(None, description='e.g. ["BII","BII UMUM"] or "BII,BII UMUM"'),
):
    is_valid, error = validate_file_upload(file)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    if document_type in (DocumentType.AUTO, DocumentType.UNKNOWN):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "explicit_type_required",
                              "message": "Verification requires an explicit document_type (KTP/SIM/STNK/KIR)"}},
        )
    from app.utils.pdf_input import normalize_upload
    contents = normalize_upload(await file.read())
    claims = {"nik": claimed_nik, "name": claimed_name, "dob": claimed_dob,
              "sim_number": claimed_sim_number, "plate": claimed_plate,
              "nomor_rangka": claimed_nomor_rangka}
    result = await _ocr_and_verify(contents, document_type, claims,
                                   _parse_required_classes(required_classes))
    return {"success": True, "document_type": document_type.value, **result}


@router.post("/trip", summary="Dispatch check: SIM + STNK + KIR in one call")
async def verify_trip(
    sim_file: Optional[UploadFile] = File(None),
    stnk_file: Optional[UploadFile] = File(None),
    kir_file: Optional[UploadFile] = File(None),
    driver_name: Optional[str] = Form(None),
    sim_number: Optional[str] = Form(None),
    plate: Optional[str] = Form(None, description="Assigned truck plate; checked on STNK and KIR"),
    nomor_rangka: Optional[str] = Form(None),
    required_classes: Optional[str] = Form(None, description='e.g. "BII,BII UMUM"'),
):
    uploads = {
        "SIM": (sim_file, {"name": driver_name, "sim_number": sim_number}),
        "STNK": (stnk_file, {"plate": plate, "nomor_rangka": nomor_rangka}),
        "KIR": (kir_file, {"plate": plate, "nomor_rangka": nomor_rangka}),
    }
    if not any(f for f, _ in uploads.values()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "no_documents", "message": "Provide at least one of sim_file, stnk_file, kir_file"}},
        )

    req_classes = _parse_required_classes(required_classes)
    doc_results: Dict[str, Dict] = {}
    for name, (upload, claims) in uploads.items():
        if upload is None:
            continue
        is_valid, error = validate_file_upload(upload)
        if not is_valid:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"{name}: {error}")
        from app.utils.pdf_input import normalize_upload
        contents = normalize_upload(await upload.read())
        doc_results[name] = await _ocr_and_verify(
            contents, DocumentType(name), claims,
            req_classes if name == "SIM" else None,
        )

    overall = aggregate_trip(doc_results)
    return {"success": True, "decision": overall["decision"],
            "documents": doc_results}
