import cv2
import numpy as np
import os

def preprocess_image_for_ocr(image_path: str) -> str:
    """
    Fast preprocessing for OCR - optimized for speed.
    Returns path to the preprocessed image.
    """
    try:
        # Read image
        image = cv2.imread(image_path)
        if image is None:
            return image_path
        
        # Fast resize if too large (performance optimization)
        height, width = image.shape[:2]
        if width > 1500 or height > 1500:
            scale = min(1500/width, 1500/height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
        
        # Fast contrast enhancement
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        enhanced = cv2.equalizeHist(gray)
        
        # Save preprocessed image
        base_name = os.path.basename(image_path)
        processed_path = f"fast_{base_name}"
        cv2.imwrite(processed_path, enhanced)
        
        return processed_path
    
    except Exception:
        # If preprocessing fails, return original
        return image_path

def detect_and_correct_skew(image: np.ndarray) -> np.ndarray:
    """
    Detect and correct skew in the image.
    """
    try:
        coords = np.column_stack(np.where(image > 0))
        if len(coords) == 0:
            return image
        
        angle = cv2.minAreaRect(coords)[-1]
        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle
        
        # Only correct if skew is significant
        if abs(angle) > 0.5:
            (h, w) = image.shape[:2]
            center = (w // 2, h // 2)
            M = cv2.getRotationMatrix2D(center, angle, 1.0)
            rotated = cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            return rotated
        
        return image
    except Exception as e:
        print(f"Skew correction error: {e}")
        return image 