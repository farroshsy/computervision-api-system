"""Single source of truth for the capture/quality guidance.

The frontend (/capture, /demo/standard) must not KNOW anything the API can't
tell it. These constants live here, the API serves them
(GET /api/v1/capture/template, /api/v1/standard), and the frontend fetches
them — so any app can build the same guided capture from the API alone.
"""
from app.config import settings

# Frame aspect ratio (width / height) per document type. KTP/SIM are ID-1
# cards (85.6 x 53.98 mm -> 1.586); STNK is a larger card; KIR is a portrait
# sheet. The shape teaches the user how to hold the document.
DOC_ASPECTS = {"KTP": 1.586, "SIM": 1.586, "STNK": 1.42, "KIR": 0.71}

# What a good photo looks like — the checklist behind the reference standard.
QUALITY_CRITERIA = [
    "Seluruh kartu masuk frame, tidak terpotong",
    "Diambil rata dari atas (tanpa miring/perspektif)",
    "Terang merata, tanpa titik silau di area teks",
    "Fokus tajam — tiap huruf terbaca mata",
    "Resolusi cukup: sisi pendek kartu >= 600 px (ideal >= 1000)",
    "Latar polos, tanpa jari/benda menutup teks",
    "Foto langsung (bukan fotokopi/scan hitam-putih)",
]

# Advisory reason codes the OCR endpoint returns for a photo that should be
# retaken — the second net after capture-time guidance.
RETAKE_REASONS = [
    "resolution_too_low", "blurry_image", "image_too_dark",
    "grayscale_possible_photocopy", "missing_card_header",
]


def capture_template() -> dict:
    """Everything an app needs to build the same guided capture UI."""
    return {
        "doc_types": {
            dt: {"frame_aspect_ratio": round(a, 3),
                 "orientation": "landscape" if a >= 1 else "portrait"}
            for dt, a in DOC_ASPECTS.items()
        },
        "quality": {
            "min_short_side_px": int(getattr(settings, "MIN_IMAGE_SHORT_SIDE", 600)),
            "recommended_short_side_px": 1000,
            "min_frame_fill_pct": 85,
            "max_skew_degrees": 5,
            "photocopy_saturation_threshold": float(
                getattr(settings, "PHOTOCOPY_SATURATION_THRESHOLD", 3.0)),
        },
        "criteria": QUALITY_CRITERIA,
        "retake_reasons": RETAKE_REASONS,
    }


def data_standard() -> dict:
    """The reference standard for collecting new data (criteria + where the
    annotated exemplar gallery lives). Exemplar images are PII, so the gallery
    is served separately from a runtime mount, not returned here."""
    return {
        "criteria": QUALITY_CRITERIA,
        "mandatory": False,
        "note": ("Acuan, bukan kewajiban. Foto lama tetap dievaluasi di /demo; "
                 "foto baru yang mengikuti standar ini menghasilkan OCR terbaik."),
        "exemplar_gallery": "/demo/standard",
        "capture_helper": "/capture",
    }
