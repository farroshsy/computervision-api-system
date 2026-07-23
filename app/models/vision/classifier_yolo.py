from typing import Optional, Dict, Any
import numpy as np


class DocTypeClassifier:
    """YOLO-based document type classifier (stub).
    Replace `predict` implementation after training/export.
    """
    def __init__(self) -> None:
        self.loaded = False  # weights not bundled yet

    def predict(self, image: np.ndarray) -> Optional[Dict[str, Any]]:
        # No-op stub returns None to keep baseline routing
        return None
