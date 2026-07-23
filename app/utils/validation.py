"""Utility functions for request validation."""
import os
from typing import Tuple, Optional
from fastapi import UploadFile, Request

# Pure-Pillow MIME detection (Windows/Docker friendly)
def _detect_mime_from_buffer(buf: bytes) -> str:
    if buf[:5] == b"%PDF-":
        return "application/pdf"
    try:
        from PIL import Image  # pillow is in requirements
        from io import BytesIO
        with Image.open(BytesIO(buf)) as img:
            fmt = (img.format or '').lower()
            if fmt in ("jpeg", "jpg"):
                return "image/jpeg"
            if fmt == "png":
                return "image/png"
            if fmt == "webp":
                return "image/webp"
    except Exception:
        pass
    return "application/octet-stream"

from app.config import settings
from app.schemas.request_models import DocumentType

def validate_file_upload(
    file: UploadFile,
    max_size_mb: int = 10,
    allowed_mime_types: Optional[list] = None,
) -> Tuple[bool, str]:
    """
    Validate an uploaded file.
    
    Args:
        file: The uploaded file to validate
        max_size_mb: Maximum allowed file size in MB
        allowed_mime_types: List of allowed MIME types. If None, uses settings.ALLOWED_MIME_TYPES
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if allowed_mime_types is None:
        allowed_mime_types = settings.ALLOWED_MIME_TYPES
    
    max_size_bytes = max_size_mb * 1024 * 1024
    
    # Check if file is empty
    if not file.filename or not file.file:
        return False, "No file provided"
    
    # Check file size
    try:
        # Move to end of file to get size
        file.file.seek(0, os.SEEK_END)
        file_size = file.file.tell()
        # Reset file pointer to the beginning
        file.file.seek(0)
        
        if file_size > max_size_bytes:
            return False, f"File size exceeds maximum allowed size of {max_size_mb}MB"
    except Exception as e:
        return False, f"[VAL2] Error checking file size: {str(e)}"
    
    # Check MIME type via Pillow-only detection (non-fatal)
    try:
        # Read first 2048 bytes for MIME type detection
        file_start = file.file.read(2048)
        file.file.seek(0)  # Reset file pointer
        
        detected_type = _detect_mime_from_buffer(file_start)
    except Exception:
        detected_type = "application/octet-stream"

    allowed_lower = [t.lower() for t in allowed_mime_types]
    if detected_type.lower() not in allowed_lower:
        # Fallback: allow based on filename extension when MIME is inconclusive
        ext = get_file_extension(file.filename or "")
        ext_to_mime = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "pdf": "application/pdf",
        }
        fallback_type = ext_to_mime.get(ext, "application/octet-stream")
        if fallback_type.lower() not in allowed_lower:
            return False, f"[VAL2] Unsupported file type: {detected_type}. Allowed types: {', '.join(allowed_mime_types)}"

    return True, ""

def validate_document_type(doc_type: str) -> Tuple[bool, str]:
    """
    Validate that a document type is supported.
    
    Args:
        doc_type: The document type to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not doc_type:
        return False, "Document type is required"
    
    if doc_type.upper() not in [dt.upper() for dt in settings.ALLOWED_DOCUMENT_TYPES]:
        return False, f"Unsupported document type: {doc_type}. Supported types: {', '.join(settings.ALLOWED_DOCUMENT_TYPES)}"
    
    return True, ""

def validate_api_key(api_key: Optional[str] = None) -> bool:
    """
    Validate an API key.
    
    Args:
        api_key: The API key to validate
        
    Returns:
        bool: True if valid, False otherwise
    """
    if not settings.REQUIRE_API_KEY:
        return True
        
    if not api_key:
        return False
        
    return api_key == settings.API_KEY

def validate_rate_limit(request: Request) -> bool:
    """
    Validate if a request is within rate limits.
    
    Args:
        request: The incoming request
        
    Returns:
        bool: True if within rate limits, False otherwise
    """
    # This is a placeholder - actual rate limiting is handled by the rate limiter middleware
    # This function can be used for additional validation if needed
    return True

def validate_confidence_threshold(threshold: float) -> Tuple[bool, str]:
    """
    Validate a confidence threshold value.
    
    Args:
        threshold: The confidence threshold to validate (0.0-1.0)
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    if not (0.0 <= threshold <= 1.0):
        return False, "Confidence threshold must be between 0.0 and 1.0"
    return True, ""

def get_file_extension(filename: str) -> str:
    """
    Get the file extension from a filename.
    
    Args:
        filename: The filename to extract extension from
        
    Returns:
        The file extension in lowercase, or empty string if no extension
    """
    if not filename:
        return ""
    
    # Split on the last dot
    parts = filename.rsplit('.', 1)
    if len(parts) == 2:
        return parts[1].lower()
    return ""
