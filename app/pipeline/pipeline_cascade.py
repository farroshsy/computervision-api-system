from typing import Optional, Dict, Any, List
import time
import os
import numpy as np

from app.config import settings
from .pipeline_base import PipelineResult
from app.models.vision.ocr_paddle import PaddleOCRRunner
from app.models.vision.classifier_yolo import DocTypeClassifier
from app.models.vision.detector_fields_yolo import FieldDetector
from app.models.vision.crop_utils import crop_boxes


class CascadePipeline:
    def __init__(self) -> None:
        # Lightweight runners; YOLO runners are stubs until models provided
        self.ocr = PaddleOCRRunner()
        self.cls = DocTypeClassifier()
        self.det = FieldDetector()
        # Env-gated enablement (do not assume constructor signatures for weights)
        self.cls_enabled: bool = bool(os.getenv("DOC_CLS_WEIGHTS"))
        self.det_enabled: bool = bool(os.getenv("FIELD_DET_WEIGHTS"))
        self.low_conf = float(settings.LOW_CONF_THRESHOLD)
        self.max_fallbacks = int(settings.MAX_FALLBACKS)

    def run(self, image: np.ndarray, doc_type_hint: Optional[str] = None) -> PipelineResult:
        start = time.time()
        meta: Dict[str, Any] = {"used_fallback": False, "confidences": {}}

        # 1) Determine doc type (hint > classifier > unknown)
        doc_type = (doc_type_hint or "").upper().strip() or None
        if (not doc_type or doc_type == "AUTO") and self.cls_enabled:
            pred = self.cls.predict(image)
            if pred and pred.get("doc_type"):
                doc_type = pred["doc_type"]
        meta["doc_type"] = doc_type or "UNKNOWN"
        meta["models"] = {
            "doc_cls": "enabled" if self.cls_enabled else "disabled",
            "field_det": "enabled" if self.det_enabled else "disabled",
        }

        # 2) Baseline OCR (full image)
        ocr_lines, ocr_meta = self.ocr.run_full_image(image)
        meta.update({"baseline": ocr_meta})

        # 3) Parse via existing route stack (left to API layer). Here we only return OCR lines.
        #    The API handler will apply current parsers/validators and decide on fallback.
        result: PipelineResult = {
            "fields": {},
            "lines": ocr_lines,
            "meta": meta,
        }

        # 4) Fallback path (detector-guided crops) — NO-OP until API layer signals need.
        #    We expose a helper to run fallback when given field names.
        return result

    def fallback_detect_and_ocr(self, image: np.ndarray, doc_type: str, field_classes: Optional[List[str]] = None) -> Dict[str, Any]:
        """Detector-guided crop OCR for specified fields. Returns {fields, crops_meta}.
        Stubbed until detector weights are provided.
        """
        if not self.det_enabled:
            return {"fields": {}, "crops_meta": [], "detector": "disabled"}
        boxes = self.det.detect(image, doc_type=doc_type, classes=field_classes)
        crops = crop_boxes(image, boxes)
        fields: Dict[str, Any] = {}
        crops_meta: List[Dict[str, Any]] = []
        for name, crop in crops:
            text, conf = self.ocr.run_single_line(crop)
            fields[name] = {"value": text, "confidence": conf}
            crops_meta.append({"field": name, "conf": conf})
        return {"fields": fields, "crops_meta": crops_meta}
