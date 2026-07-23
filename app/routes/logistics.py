"""Logistics endpoints: ISO 6346 container number validation.

Two modes:
- text: validate a known number (weighbridge/gate systems already have
  the string, they want the arithmetic proof)
- image: OCR a gate/door photo, find container-shaped tokens, validate
  each (port gate automation)
"""
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.concurrency import run_in_threadpool

from app.services.paddle_ocr import extract_text_from_image
from app.utils.container_check import find_container_numbers, validate_container_number
from app.utils.validation import validate_file_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/logistics", tags=["logistics"])


@router.post("/container", summary="Validate ISO 6346 container number (text or photo)")
async def container_validate(
    container_number: Optional[str] = Form(None, description="e.g. CSQU3054383"),
    file: Optional[UploadFile] = File(None, description="Gate/door photo to OCR"),
):
    if container_number:
        return {"success": True, "results": [validate_container_number(container_number)]}
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "missing_input",
                              "message": "Provide container_number or an image file"}},
        )
    is_valid, error = validate_file_upload(file)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    contents = await file.read()
    lines = await run_in_threadpool(extract_text_from_image, contents)
    results = find_container_numbers(" ".join(lines))
    return {"success": True, "lines_read": len(lines), "results": results}
