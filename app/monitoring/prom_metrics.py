"""
Prometheus metrics for OCR-specific instrumentation.
These metrics complement the in-memory metrics in app.monitoring.metrics
and are exported via the existing /metrics endpoint in app/main.py.
"""
from typing import Optional
from prometheus_client import Histogram, Counter

# OCR latency histogram (seconds)
ocr_latency = Histogram(
    "ocr_latency_seconds",
    "OCR latency in seconds",
    ["pipeline_mode"],
    buckets=[0.1, 0.5, 1, 2, 5, 10]
)

# OCR requests counter labeled by pipeline and status.
# NOTE: named ocr_pipeline_requests_total to avoid clashing with
# ocr_requests_total registered in app/metrics.py (document_type/status labels);
# duplicate registration raises ValueError at import and prevents app boot.
ocr_requests = Counter(
    "ocr_pipeline_requests_total",
    "OCR requests count per pipeline mode",
    ["pipeline_mode", "status"]
)

# OCR fallback counter labeled by pipeline
ocr_fallback = Counter(
    "ocr_fallback_total",
    "OCR fallback triggered",
    ["pipeline_mode"]
)

def record_prom_ocr_metrics(
    *,
    pipeline_mode: str,
    status: str,
    latency_seconds: Optional[float] = None,
    used_fallback: Optional[bool] = None,
) -> None:
    """Record OCR Prometheus metrics.

    Args:
        pipeline_mode: logical pipeline label, e.g. "baseline" or "cascade".
        status: "success" or "failed" (free-form, used as a label).
        latency_seconds: duration of the request in seconds.
        used_fallback: if True, increments the fallback counter for the pipeline.
    """
    try:
        # Normalize labels
        mode = (pipeline_mode or "baseline").lower()
        st = (status or "unknown").lower()

        ocr_requests.labels(pipeline_mode=mode, status=st).inc()
        if latency_seconds is not None:
            try:
                ocr_latency.labels(pipeline_mode=mode).observe(float(latency_seconds))
            except Exception:
                # Never crash on bad inputs
                pass
        if used_fallback:
            ocr_fallback.labels(pipeline_mode=mode).inc()
    except Exception:
        # Defensive: Prom instrumentation must never raise
        pass
