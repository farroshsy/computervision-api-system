import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
from app.config import settings
from app.monitoring.prom_metrics import record_prom_ocr_metrics

@dataclass
class RequestMetrics:
    """Class to track metrics for API requests."""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_processing_time: float = 0.0
    endpoint_metrics: Dict[str, Dict] = field(default_factory=dict)
    error_codes: Dict[int, int] = field(default_factory=dict)
    recent_requests: List[Dict] = field(default_factory=list)
    
    def record_request(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        processing_time: float,
        error: Optional[str] = None
    ) -> None:
        """Record a new request with its metrics."""
        self.total_requests += 1
        self.total_processing_time += processing_time
        
        if 200 <= status_code < 400:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
            self.error_codes[status_code] = self.error_codes.get(status_code, 0) + 1
        
        # Update endpoint-specific metrics
        if endpoint not in self.endpoint_metrics:
            self.endpoint_metrics[endpoint] = {
                'total': 0,
                'success': 0,
                'errors': 0,
                'total_time': 0.0,
                'avg_time': 0.0,
                'methods': {}
            }
        
        endpoint_metric = self.endpoint_metrics[endpoint]
        endpoint_metric['total'] += 1
        endpoint_metric['total_time'] += processing_time
        endpoint_metric['avg_time'] = endpoint_metric['total_time'] / endpoint_metric['total']
        
        if 200 <= status_code < 400:
            endpoint_metric['success'] += 1
        else:
            endpoint_metric['errors'] += 1
        
        # Track methods
        if method not in endpoint_metric['methods']:
            endpoint_metric['methods'][method] = 0
        endpoint_metric['methods'][method] += 1
        
        # Track recent requests (keep last 100)
        self.recent_requests.append({
            'timestamp': datetime.utcnow().isoformat(),
            'endpoint': endpoint,
            'method': method,
            'status_code': status_code,
            'processing_time': processing_time,
            'error': error
        })
        self.recent_requests = self.recent_requests[-100:]  # Keep only last 100 requests
        
        logger.info(
            f"Request: {method} {endpoint} | "
            f"Status: {status_code} | "
            f"Time: {processing_time:.2f}ms"
        )
    
    def get_metrics_summary(self) -> Dict:
        """Get a summary of all collected metrics."""
        avg_processing_time = (
            self.total_processing_time / self.total_requests 
            if self.total_requests > 0 else 0
        )
        
        return {
            'total_requests': self.total_requests,
            'successful_requests': self.successful_requests,
            'failed_requests': self.failed_requests,
            'success_rate': (
                (self.successful_requests / self.total_requests * 100) 
                if self.total_requests > 0 else 100
            ),
            'avg_processing_time_ms': avg_processing_time,
            'endpoint_metrics': self.endpoint_metrics,
            'error_distribution': self.error_codes,
            'uptime_seconds': (datetime.utcnow() - self._start_time).total_seconds()
        }
    
    def reset_metrics(self) -> None:
        """Reset all metrics."""
        self.__init__()

# Global metrics instance
metrics = RequestMetrics()
metrics._start_time = datetime.utcnow()  # Track when metrics collection started


# -----------------------------
# Field-level extraction metrics
# -----------------------------
@dataclass
class FieldStat:
    total: int = 0
    success: int = 0
    missing: int = 0
    below_threshold: int = 0
    relaxed_used: int = 0
    total_confidence: float = 0.0
    avg_confidence: float = 0.0
    reasons: Dict[str, int] = field(default_factory=dict)


_field_metrics: Dict[str, FieldStat] = {}


def record_field_extraction(
    field_name: str,
    status: str,
    confidence: Optional[float] = None,
    mode: Optional[str] = None,
    reason: Optional[str] = None,
) -> None:
    """Record a single field extraction outcome.

    status: one of ['success', 'missing', 'below_threshold']
    mode: 'relaxed' or None
    """
    stat = _field_metrics.setdefault(field_name, FieldStat())
    stat.total += 1
    if status == 'success':
        stat.success += 1
    elif status == 'missing':
        stat.missing += 1
    elif status == 'below_threshold':
        stat.below_threshold += 1
    if mode == 'relaxed':
        stat.relaxed_used += 1
    if confidence is not None:
        stat.total_confidence += float(confidence)
        stat.avg_confidence = stat.total_confidence / max(1, stat.total)
    if reason:
        stat.reasons[reason] = stat.reasons.get(reason, 0) + 1


def get_field_metrics() -> Dict[str, Dict]:
    """Return a serializable snapshot of field-level metrics."""
    out: Dict[str, Dict] = {}
    for name, s in _field_metrics.items():
        out[name] = {
            'total': s.total,
            'success': s.success,
            'missing': s.missing,
            'below_threshold': s.below_threshold,
            'relaxed_used': s.relaxed_used,
            'avg_confidence': s.avg_confidence,
            'reasons': dict(s.reasons),
        }
    return out


def record_ocr_metrics(
    document_type: str,
    processing_time: float,
    success: bool,
    error: Optional[str] = None,
    ocr_engine: str = "paddleocr",
    pipeline_mode: Optional[str] = None,
    used_fallback: Optional[bool] = None,
) -> None:
    """Record metrics specific to OCR processing."""
    if not hasattr(record_ocr_metrics, 'ocr_metrics'):
        record_ocr_metrics.ocr_metrics = {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'total_processing_time': 0.0,
            'by_document_type': {},
            'by_engine': {},
            'by_pipeline_mode': {},
            'fallback_counters': {},
            'errors': {}
        }
    
    ocr_metrics = record_ocr_metrics.ocr_metrics
    ocr_metrics['total_processed'] += 1
    ocr_metrics['total_processing_time'] += processing_time
    
    if success:
        ocr_metrics['successful'] += 1
    else:
        ocr_metrics['failed'] += 1
        if error:
            ocr_metrics['errors'][error] = ocr_metrics['errors'].get(error, 0) + 1
    
    # Track by document type
    if document_type not in ocr_metrics['by_document_type']:
        ocr_metrics['by_document_type'][document_type] = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'total_time': 0.0
        }
    
    doc_metrics = ocr_metrics['by_document_type'][document_type]
    doc_metrics['total'] += 1
    doc_metrics['total_time'] += processing_time
    
    if success:
        doc_metrics['success'] += 1
    else:
        doc_metrics['failed'] += 1
    
    # Track by OCR engine
    if ocr_engine not in ocr_metrics['by_engine']:
        ocr_metrics['by_engine'][ocr_engine] = {
            'total': 0,
            'total_time': 0.0,
            'avg_time': 0.0
        }
    
    engine_metrics = ocr_metrics['by_engine'][ocr_engine]
    engine_metrics['total'] += 1
    engine_metrics['total_time'] += processing_time
    engine_metrics['avg_time'] = engine_metrics['total_time'] / engine_metrics['total']

    # Track by pipeline mode (label)
    mode = (pipeline_mode or 'baseline')
    if mode not in ocr_metrics['by_pipeline_mode']:
        ocr_metrics['by_pipeline_mode'][mode] = {
            'total': 0,
            'success': 0,
            'failed': 0,
            'total_time': 0.0,
            'avg_time': 0.0,
        }
    m = ocr_metrics['by_pipeline_mode'][mode]
    m['total'] += 1
    m['total_time'] += processing_time
    m['avg_time'] = m['total_time'] / m['total']
    if success:
        m['success'] += 1
    else:
        m['failed'] += 1

    # Fallback counter
    if used_fallback:
        ocr_metrics['fallback_counters'][mode] = ocr_metrics['fallback_counters'].get(mode, 0) + 1
    
    logger.debug(
        f"OCR Processed: {document_type} | "
        f"Success: {success} | "
        f"Time: {processing_time:.2f}ms"
    )

    # Emit Prometheus metrics (defensive: never raise)
    try:
        if getattr(settings, "ENABLE_METRICS", True):
            record_prom_ocr_metrics(
                pipeline_mode=mode,
                status=("success" if success else "failed"),
                latency_seconds=float(processing_time),
                used_fallback=bool(used_fallback),
            )
    except Exception:
        pass


def get_ocr_metrics() -> Dict:
    """Get a summary of OCR-specific metrics."""
    if not hasattr(record_ocr_metrics, 'ocr_metrics'):
        return {
            'total_processed': 0,
            'successful': 0,
            'failed': 0,
            'by_document_type': {},
            'by_engine': {},
            'errors': {}
        }
    
    ocr_metrics = record_ocr_metrics.ocr_metrics.copy()
    
    # Calculate success rate
    total = ocr_metrics['total_processed']
    ocr_metrics['success_rate'] = (
        (ocr_metrics['successful'] / total * 100) if total > 0 else 100
    )
    
    # Calculate average processing time
    ocr_metrics['avg_processing_time_ms'] = (
        ocr_metrics['total_processing_time'] / total if total > 0 else 0
    )
    
    # Calculate success rates for document types
    for doc_type, metrics in ocr_metrics['by_document_type'].items():
        total = metrics['total']
        metrics['success_rate'] = (
            (metrics['success'] / total * 100) if total > 0 else 0
        )
        metrics['avg_processing_time_ms'] = (
            metrics['total_time'] / total if total > 0 else 0
        )
    
    return ocr_metrics
