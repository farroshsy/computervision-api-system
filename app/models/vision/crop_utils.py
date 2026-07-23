from typing import List, Tuple
import numpy as np


def crop_boxes(image: np.ndarray, boxes: List[Tuple[str, int, int, int, int, float]]):
    """Yield (name, crop) for each box in boxes.
    Boxes: (name, x1, y1, x2, y2, score)
    """
    h, w = image.shape[:2]
    out = []
    for name, x1, y1, x2, y2, score in boxes:
        xx1 = max(0, min(int(x1), w - 1))
        yy1 = max(0, min(int(y1), h - 1))
        xx2 = max(0, min(int(x2), w - 1))
        yy2 = max(0, min(int(y2), h - 1))
        if xx2 <= xx1 or yy2 <= yy1:
            continue
        crop = image[yy1:yy2, xx1:xx2].copy()
        out.append((name, crop))
    return out
