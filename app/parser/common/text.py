"""
Lightweight shared text helpers for parsers.
This module is a placeholder for future shared cleaners, regex patterns,
and small utilities reused by KTP/SIM/STNK/KIR extractors.
"""

from typing import Dict, Any


def package_result(value: str, base_conf: float, provenance: Dict[str, Any]) -> Dict[str, Any]:
    """Package a value with confidence and provenance in a consistent format.
    Note: KTP extractors may still use their internal packagers; this provides a
    common shape for new extractors.
    """
    return {
        "value": value,
        "confidence": float(max(0.0, min(1.0, base_conf))),
        "provenance": provenance or {},
    }
