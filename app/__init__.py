"""
OCR API package initialization.
"""
from .metrics import setup_metrics, track_ocr_processing, Timer

__all__ = [
    'setup_metrics',
    'track_ocr_processing',
    'Timer',
]