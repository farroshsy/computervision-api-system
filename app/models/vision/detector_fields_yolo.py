from typing import List, Dict, Any, Optional, Tuple
import numpy as np


class FieldDetector:
    """YOLO-based field detector (stub).
    Returns list of boxes as (name, x1, y1, x2, y2, score).
    """
    def __init__(self) -> None:
        self.loaded = False

    def detect(self, image: np.ndarray, doc_type: Optional[str] = None, classes: Optional[List[str]] = None) -> List[Tuple[str, int, int, int, int, float]]:
        return []
