"""Capture / data-standard guidance as a proper JSON API.

Whatever the frontend knows about how to capture a good photo and what the
data standard is, an integrator can get from the API alone — no page scraping.
"""
from fastapi import APIRouter

from app.services.capture_spec import capture_template, data_standard

router = APIRouter(prefix="/api/v1", tags=["guidance"])


@router.get("/capture/template", summary="Per-doctype frame geometry + quality spec for building a guided capture UI")
async def get_capture_template() -> dict:
    return capture_template()


@router.get("/standard", summary="Reference standard (quality criteria) for collecting new document photos")
async def get_data_standard() -> dict:
    return data_standard()
