from typing import Protocol, TypedDict, Optional, Dict, Any, List
import numpy as np


class PipelineResult(TypedDict, total=False):
    fields: Dict[str, Any]
    lines: List[str]
    meta: Dict[str, Any]  # {doc_type, used_fallback, processing_time_ms, confidences}


class Pipeline(Protocol):
    def run(self, image: np.ndarray, doc_type_hint: Optional[str] = None) -> PipelineResult: ...
