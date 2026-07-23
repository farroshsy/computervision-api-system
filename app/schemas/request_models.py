"""Pydantic models for request validation."""
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, ClassVar
from pydantic import BaseModel, Field, HttpUrl, field_validator, ConfigDict, model_validator

class DocumentType(str, Enum):
    """Supported document types for OCR processing."""
    KTP = "KTP"
    SIM = "SIM"
    STNK = "STNK"
    KIR = "KIR"
    AUTO = "AUTO"  # Let the system auto-detect from OCR text
    UNKNOWN = "UNKNOWN"  # Detection failed / ambiguous

class BaseRequest(BaseModel):
    """Base request model with common fields."""
    document_type: DocumentType = Field(
        ...,
        description="Type of document to process",
        json_schema_extra={"examples": ["AUTO", "KTP", "SIM", "STNK", "KIR"]}
    )
    confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence threshold for OCR results (0.0-1.0)",
        json_schema_extra={"example": 0.7}
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_type": "AUTO",
                "confidence_threshold": 0.7
            }
        },
        use_enum_values=True,
        str_strip_whitespace=True
    )

class FileUploadRequest(BaseRequest):
    """Request model for file uploads."""
    file: bytes = Field(
        ...,
        description="Binary file data to process",
        json_schema_extra={"example": "(binary data)"}
    )
    filename: str = Field(
        ...,
        description="Original filename with extension",
        json_schema_extra={"example": "ktp_image.jpg"}
    )
    content_type: str = Field(
        ...,
        description="MIME type of the file",
        json_schema_extra={"example": "image/jpeg"}
    )
    
    @field_validator('content_type')
    @classmethod
    def validate_content_type(cls, v: str) -> str:
        """Validate that the content type is allowed."""
        allowed_types = ["image/jpeg", "image/png", "image/jpg"]
        if v.lower() not in allowed_types:
            raise ValueError(f"Unsupported file type. Allowed types: {', '.join(allowed_types)}")
        return v.lower()
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_type": "AUTO",
                "confidence_threshold": 0.7,
                "filename": "ktp_image.jpg",
                "content_type": "image/jpeg"
            }
        },
        use_enum_values=True,
        str_strip_whitespace=True
    )

class URLRequest(BaseRequest):
    """Request model for processing documents from a URL."""
    image_url: HttpUrl = Field(
        ...,
        description="URL of the image to process",
        json_schema_extra={"example": "https://example.com/ktp_image.jpg"}
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_type": "AUTO",
                "confidence_threshold": 0.7,
                "image_url": "https://example.com/ktp_image.jpg"
            }
        },
        use_enum_values=True,
        str_strip_whitespace=True
    )

class FieldExtraction(BaseModel):
    """Model for extracted field data."""
    value: Optional[str] = None
    confidence: float = 0.0
    raw_text: Optional[str] = None
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "value": "John Doe",
                "confidence": 0.95,
                "raw_text": "Nama : John Doe"
            }
        }
    )

class OCRResponse(BaseModel):
    """Response model for OCR processing results."""
    success: bool = Field(
        ...,
        description="Whether the request was successful",
        json_schema_extra={"example": True}
    )
    document_type: str = Field(
        ...,
        description="Type of document that was processed",
        json_schema_extra={"example": "KTP"}
    )
    processing_time: float = Field(
        ...,
        description="Total processing time in seconds",
        json_schema_extra={"example": 1.23}
    )
    timestamp: float = Field(
        ...,
        description="Unix timestamp when the processing completed",
        json_schema_extra={"example": 1678901234.567}
    )
    data: Dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted data from the document"
    )
    meta: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional metadata for observability (e.g., pipeline mode, thresholds, fallback info)"
    )
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "document_type": "KTP",
                "processing_time": 1.23,
                "timestamp": 1678901234.567,
                "data": {
                    "raw_text": "...",
                    "fields": {
                        "name": {
                            "value": "John Doe",
                            "confidence": 0.95,
                            "raw_text": "Nama : John Doe"
                        }
                    }
                },
                "meta": {
                    "pipeline_mode": "baseline",
                    "used_fallback": False,
                    "low_conf_threshold": 0.7,
                    "max_fallbacks": 1,
                    "min_fields_for_pass": 3
                }
            }
        }
    )

class ErrorResponse(BaseModel):
    """Standard error response model."""
    error: Dict[str, Any] = Field(
        ...,
        description="Error details",
        json_schema_extra={
            "example": {
                "code": "validation_error",
                "message": "Invalid request data",
                "details": {"field": "value"}
            }
        }
    )
    
    @classmethod
    def create(
        cls,
        code: str,
        message: str,
        details: Optional[Dict[str, Any]] = None,
        status_code: int = 400
    ) -> Dict[str, Any]:
        """Create a standardized error response."""
        error_data = {
            "code": code,
            "message": message,
        }
        if details:
            error_data["details"] = details
            
        return {
            "error": error_data,
            "status_code": status_code
        }
