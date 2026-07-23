from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import os
from typing import Dict, Any
import logging

from app.monitoring.metrics import metrics, get_ocr_metrics, get_field_metrics

logger = logging.getLogger(__name__)
router = APIRouter(tags=["monitoring"])

# Basic authentication for metrics endpoints
security = HTTPBearer()
METRICS_API_KEY = os.getenv("METRICS_API_KEY", "default-metrics-key")

def verify_auth(credentials: HTTPAuthorizationCredentials = Depends(security)) -> None:
    """Verify the provided API key for metrics endpoints."""
    if credentials.scheme != "Bearer" or credentials.credentials != METRICS_API_KEY:
        logger.warning("Unauthorized access attempt to metrics endpoint")
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

@router.get("/metrics/health", response_model=Dict[str, Any])
async def get_health_metrics() -> Dict[str, Any]:
    """Get basic health metrics for the API."""
    return {
        "status": "healthy",
        "metrics": {
            "total_requests": metrics.total_requests,
            "success_rate": (
                (metrics.successful_requests / metrics.total_requests * 100)
                if metrics.total_requests > 0
                else 100
            ),
            "avg_processing_time_ms": (
                metrics.total_processing_time / metrics.total_requests
                if metrics.total_requests > 0
                else 0
            ),
            "endpoints": list(metrics.endpoint_metrics.keys()),
        },
    }

@router.get("/metrics/requests", response_model=Dict[str, Any], dependencies=[Depends(verify_auth)])
async def get_request_metrics() -> Dict[str, Any]:
    """Get detailed request metrics (requires authentication)."""
    return metrics.get_metrics_summary()

@router.get("/metrics/ocr", response_model=Dict[str, Any], dependencies=[Depends(verify_auth)])
async def get_ocr_metrics_endpoint() -> Dict[str, Any]:
    """Get OCR-specific metrics (requires authentication)."""
    return get_ocr_metrics()

@router.get("/metrics/full", response_model=Dict[str, Any], dependencies=[Depends(verify_auth)])
async def get_all_metrics() -> Dict[str, Any]:
    """Get all available metrics (requires authentication)."""
    return {
        "request_metrics": metrics.get_metrics_summary(),
        "ocr_metrics": get_ocr_metrics(),
        "system": {
            "python_version": "3.10.0",  # This should be dynamic in production
            "environment": os.getenv("ENV", "development"),
        },
    }

@router.get("/metrics/fields", response_model=Dict[str, Any], dependencies=[Depends(verify_auth)])
async def get_field_level_metrics() -> Dict[str, Any]:
    """Get field-level extraction metrics (requires authentication)."""
    return get_field_metrics()

@router.post("/metrics/reset", status_code=204, dependencies=[Depends(verify_auth)])
async def reset_metrics() -> None:
    """Reset all collected metrics (requires authentication)."""
    metrics.reset_metrics()
    # Reset OCR metrics
    if hasattr(get_ocr_metrics, 'ocr_metrics'):
        get_ocr_metrics.ocr_metrics = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'total_processing_time': 0.0,
            'by_document_type': {},
            'by_engine': {},
            'errors': {}
        }
    logger.info("Metrics have been reset")
