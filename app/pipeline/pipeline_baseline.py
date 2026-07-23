from typing import Optional, Dict, Any
import time
import numpy as np

from .pipeline_base import PipelineResult


def run(image: np.ndarray, doc_type_hint: Optional[str] = None) -> PipelineResult:
    """Baseline pipeline stub.
    Current API already implements baseline path inside `app.routes.ocr`.
    This stub exists to standardize the interface for future wiring.
    """
    start = time.time()
    # No-op: leave extraction/parsing to existing route for now.
    return {
        "fields": {},
        "meta": {
            "doc_type": doc_type_hint or "UNKNOWN",
            "used_fallback": False,
            "processing_time_ms": int((time.time() - start) * 1000),
            "confidences": {},
        },
    }
