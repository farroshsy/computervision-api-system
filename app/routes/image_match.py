"""Image fingerprint/duplicate-check endpoints.

Stateless by design: this service computes fingerprints and compares them;
the caller stores fingerprints in their own database next to their images.
No image or fingerprint is persisted here.

Typical integration (client-side pseudocode):
  1. Backfill: for each archived image -> POST /image/fingerprint ->
     store the returned string in your DB.
  2. On new upload -> POST /image/match with the upload + the stored
     fingerprint list (or a pre-filtered subset) -> reject/flag duplicates.
"""
import json
import logging
from typing import List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app.utils.image_fingerprint import (
    compare_fingerprints,
    compute_fingerprint,
    parse_fingerprint,
)
from app.utils.validation import validate_file_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/image", tags=["image-match"])

# Hard cap on candidates per request; 64-bit hash comparisons are cheap
# (~1M/s) but request payloads should stay bounded.
MAX_CANDIDATES = 10_000


class MatchResult(BaseModel):
    index: int
    dhash_distance: int
    phash_distance: int
    similarity: float
    verdict: str


@router.post("/fingerprint", summary="Compute a perceptual fingerprint for an image")
async def image_fingerprint(file: UploadFile = File(...)):
    is_valid, error = validate_file_upload(file)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    contents = await file.read()
    fp = compute_fingerprint(contents)
    if fp is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "invalid_image", "message": "Unable to decode image bytes"}},
        )
    return {"success": True, **fp}


@router.post("/match", summary="Match an uploaded image against stored fingerprints")
async def image_match(
    file: UploadFile = File(..., description="New image to check"),
    candidates: str = Form(..., description='JSON array of fingerprint strings ("v1:..:..")'),
    max_results: int = Form(5, ge=1, le=100, description="Return at most this many best matches"),
):
    is_valid, error = validate_file_upload(file)
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error)
    try:
        cand_list: List[str] = json.loads(candidates)
        assert isinstance(cand_list, list)
    except (json.JSONDecodeError, AssertionError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "invalid_candidates", "message": "candidates must be a JSON array of fingerprint strings"}},
        )
    if len(cand_list) > MAX_CANDIDATES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={"error": {"code": "too_many_candidates", "message": f"At most {MAX_CANDIDATES} candidates per request"}},
        )

    contents = await file.read()
    fp = compute_fingerprint(contents)
    if fp is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": {"code": "invalid_image", "message": "Unable to decode image bytes"}},
        )

    results: List[MatchResult] = []
    invalid_count = 0
    for i, cand in enumerate(cand_list):
        cmp = compare_fingerprints(fp["fingerprint"], cand)
        if cmp is None:
            invalid_count += 1
            continue
        results.append(MatchResult(index=i, **cmp))
    results.sort(key=lambda r: (min(r.dhash_distance, r.phash_distance)))

    top = results[:max_results]
    return {
        "success": True,
        "fingerprint": fp["fingerprint"],
        "candidates_checked": len(results),
        "candidates_invalid": invalid_count,
        "duplicate_found": any(r.verdict == "duplicate" for r in results),
        "matches": [r.model_dump() for r in top],
    }
