"""
Prometheus metrics configuration and instrumentation.
"""
from typing import Callable, List, Optional, Tuple, Dict, Any, Union
from fastapi import Request, Response
from prometheus_fastapi_instrumentator import Instrumentator, metrics
from prometheus_fastapi_instrumentator.metrics import Info
from prometheus_client import Counter, Histogram
import time
import re

from .config import settings

# Define custom metrics
REQUEST_COUNT = Counter(
    'http_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_LATENCY = Histogram(
    'http_request_duration_seconds',
    'HTTP request latency in seconds',
    ['method', 'endpoint']
)

# Custom metrics for OCR operations
OCR_REQUEST_COUNT = Counter(
    'ocr_requests_total',
    'Total OCR processing requests',
    ['document_type', 'status']
)

OCR_PROCESSING_TIME = Histogram(
    'ocr_processing_seconds',
    'Time spent processing OCR operations',
    ['document_type']
)

def setup_metrics(app):
    """Set up Prometheus metrics collection for the FastAPI application."""
    if not settings.ENABLE_METRICS:
        return
    
    # Create instrumentator instance
    instrumentator = Instrumentator(
        should_group_status_codes=True,
        should_ignore_untemplated=True,
        should_respect_env_var=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=[
            settings.METRICS_PATH,
            "/health" if settings.METRICS_EXCLUDE_HEALTH else "",
            "/docs" if settings.METRICS_EXCLUDE_DOCS else "",
            "/redoc" if settings.METRICS_EXCLUDE_DOCS else "",
            "/openapi.json" if settings.METRICS_EXCLUDE_DOCS else "",
        ],
    )
    
    # Add default metrics
    instrumentator.add(metrics.default())
    
    # Add custom metrics
    instrumentator.add(
        metrics.request_size(
            should_include_handler=True,
            should_include_method=True,
            should_include_status=True,
            metric_namespace="app",
            metric_subsystem="http",
        )
    )
    
    instrumentator.add(
        metrics.latency(
            should_include_handler=True,
            should_include_method=True,
            should_include_status=True,
            metric_namespace="app",
            metric_subsystem="http",
        )
    )
    
    # Add custom metrics for request count and latency
    def http_requests_total(info: Info) -> None:
        if info.response and hasattr(info.response, "status_code"):
            REQUEST_COUNT.labels(
                method=info.request.method,
                endpoint=info.modified_handler,
                status_code=info.response.status_code
            ).inc()
    
    def http_request_duration_seconds(info: Info) -> None:
        if info.response and hasattr(info.response, "status_code"):
            REQUEST_LATENCY.labels(
                method=info.request.method,
                endpoint=info.modified_handler,
            ).observe(info.modified_duration)
    
    # Add custom metrics to instrumentator
    instrumentator.add(http_requests_total)
    instrumentator.add(http_request_duration_seconds)
    
    # Instrument the application
    instrumentator.instrument(app).expose(
        app,
        endpoint=settings.METRICS_PATH.strip("/"),
        include_in_schema=settings.ENABLE_METRICS
    )

def track_ocr_processing(document_type: str, status: str, duration: float):
    """Track OCR processing metrics."""
    if not settings.ENABLE_METRICS:
        return
    
    OCR_REQUEST_COUNT.labels(
        document_type=document_type,
        status=status
    ).inc()
    
    OCR_PROCESSING_TIME.labels(
        document_type=document_type
    ).observe(duration)

# Context manager for timing operations
class Timer:
    def __init__(self, document_type: str):
        self.document_type = document_type
        self.start_time = None
        
    def __enter__(self):
        self.start_time = time.time()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time is not None:
            duration = time.time() - self.start_time
            status = "success" if exc_type is None else "error"
            track_ocr_processing(self.document_type, status, duration)
