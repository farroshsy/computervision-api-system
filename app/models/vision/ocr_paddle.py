from typing import List, Tuple, Dict, Any
import os
import tempfile
import numpy as np
import cv2

from app.services.paddle_ocr import OCRService


class PaddleOCRRunner:
    """Lightweight wrapper around existing OCRService to work with numpy images."""
    def __init__(self) -> None:
        self.svc = OCRService()

    def _save_temp_image(self, image: np.ndarray, prefix: str = "tmp_ocr_") -> str:
        fd, path = tempfile.mkstemp(prefix=prefix, suffix=".jpg")
        os.close(fd)
        try:
            # Ensure BGR uint8
            if image.dtype != np.uint8:
                img = image.astype(np.uint8)
            else:
                img = image
            if len(img.shape) == 2:
                to_write = img
            else:
                to_write = cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if img.shape[2] == 3 else img
            cv2.imwrite(path, to_write)
            return path
        except Exception:
            # Best-effort fallback
            cv2.imwrite(path, image)
            return path

    def run_full_image(self, image: np.ndarray, doc_type: str | None = None) -> Tuple[List[str], Dict[str, Any]]:
        path = self._save_temp_image(image)
        lines, confs = self.svc.extract_text(path, doc_type=doc_type)
        meta = {
            "avg_conf": round(float(sum(confs) / len(confs)), 3) if confs else 0.0,
            "num_lines": len(lines),
        }
        return lines, meta

    def run_single_line(self, image: np.ndarray) -> Tuple[str, float]:
        """Run OCR on a small crop and return a best-effort single string and confidence."""
        lines, meta = self.run_full_image(image)
        if not lines:
            return "", 0.0
        # Choose the longest string as proxy; OCRService doesn't return per-line confs directly
        best = max(lines, key=lambda s: len(s or ""))
        return best, float(meta.get("avg_conf", 0.0))
