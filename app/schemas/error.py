"""Error handling schemas and utilities."""
from enum import Enum
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, ConfigDict, Field


class ErrorCode(str, Enum):
    """Standard error codes for the API."""
    # Client errors (4xx)
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    
    # Server errors (5xx)
    INTERNAL_SERVER_ERROR = "internal_server_error"
    SERVICE_UNAVAILABLE = "service_unavailable"
    
    @classmethod
    def from_status_code(cls, status_code: int) -> 'ErrorCode':
        """Get the appropriate error code for an HTTP status code."""
        if status_code == 400:
            return cls.VALIDATION_ERROR
        elif status_code == 401:
            return cls.UNAUTHORIZED
        elif status_code == 403:
            return cls.FORBIDDEN
        elif status_code == 404:
            return cls.NOT_FOUND
        elif status_code == 413:
            return cls.PAYLOAD_TOO_LARGE
        elif status_code == 415:
            return cls.UNSUPPORTED_MEDIA_TYPE
        elif status_code == 503:
            return cls.SERVICE_UNAVAILABLE
        else:
            return cls.INTERNAL_SERVER_ERROR


class ErrorResponse(BaseModel):
    """Standard error response format."""
    error: Dict[str, Any]
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "error": {
                    "code": "validation_error",
                    "message": "Invalid request data",
                    "details": ["field required: field_name"]
                }
            }
        }
    )


def create_error_response(
    status_code: int,
    error_code: ErrorCode,
    message: str,
    details: Optional[Any] = None
) -> Dict[str, Any]:
    """Create a standardized error response.
    
    Args:
        status_code: HTTP status code
        error_code: Standard error code
        message: Human-readable error message
        details: Additional error details (e.g., validation errors)
        
    Returns:
        Formatted error response dictionary
    """
    error_dict = {
        "code": error_code.value,
        "message": message
    }
    
    if details is not None:
        error_dict["details"] = details
    
    return {"error": error_dict}
