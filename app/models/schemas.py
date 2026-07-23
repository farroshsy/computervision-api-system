"""
Parser Context and Schemas

This module contains the ParserContext class and related schemas used for parsing KTP documents.
"""

from typing import Dict, List, Any, Optional
import re
import logging

class ParserContext:
    """
    Context class that holds the state during KTP document parsing.
    
    This class maintains the raw and cleaned lines of text from the OCR output,
    the fields that have been extracted so far, and provides logging capabilities.
    """
    
    def __init__(self, raw_lines: List[str], cleaned_lines: Optional[List[str]] = None, 
                 extracted_fields: Optional[Dict[str, Any]] = None, debug: bool = False,
                 strict_admin_filter: bool = True,
                 enforce_vowel_check: bool = True,
                 allow_standalone_address: bool = True,
                 allow_standalone_kelurahan: bool = True,
                 structured_output: bool = False,
                 # Behavior toggles (default to current permissive behavior; can be tightened in prod)
                 allow_next_line_raw_tokens: bool = True,
                 allow_tokenized_line_reconstruction: bool = True):
        """
        Initialize the parser context.
        
        Args:
            raw_lines: The original lines of text from OCR
            cleaned_lines: The cleaned/preprocessed lines of text (optional)
            extracted_fields: Dictionary to store extracted fields (optional)
            debug: Whether to enable debug logging
        """
        self.raw_lines = raw_lines
        self.cleaned_lines = cleaned_lines if cleaned_lines is not None else []
        self.fields: Dict[str, Any] = extracted_fields if extracted_fields is not None else {}
        self.extracted_fields = self.fields  # For backward compatibility
        self.debug = debug
        self.logger = logging.getLogger(__name__)
        # Parser behavior flags (config-driven, default to safe/strict)
        self.strict_admin_filter = strict_admin_filter
        self.enforce_vowel_check = enforce_vowel_check
        self.allow_standalone_address = allow_standalone_address
        self.allow_standalone_kelurahan = allow_standalone_kelurahan
        # Controls whether extractors should return structured dicts or plain strings
        self.structured_output = structured_output
        # Feature toggles for extractor behavior
        self.allow_next_line_raw_tokens = allow_next_line_raw_tokens
        self.allow_tokenized_line_reconstruction = allow_tokenized_line_reconstruction
        # Cache for computed OCR quality
        self._ocr_quality: Optional[float] = None
    
    def log_info(self, message: str, **kwargs) -> None:
        """Log an info message with additional context."""
        items = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        self.logger.info(f"{message} | {items}")
    
    def log_debug(self, message: str, **kwargs) -> None:
        """Log a debug message with additional context if debug is enabled."""
        if self.debug:
            items = " | ".join(f"{k}={v}" for k, v in kwargs.items())
            self.logger.debug(f"{message} | {items}")
    
    def log_warning(self, message: str, **kwargs) -> None:
        """Log a warning message with additional context."""
        items = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        self.logger.warning(f"{message} | {items}")
    
    def log_error(self, message: str, **kwargs) -> None:
        """Log an error message with additional context."""
        items = " | ".join(f"{k}={v}" for k, v in kwargs.items())
        self.logger.error(f"{message} | {items}")
    
    def add_field(self, field_name: str, value: Any, confidence: float = 1.0, provenance: Optional[Dict[str, Any]] = None) -> None:
        """
        Add an extracted field to the context.
        
        Args:
            field_name: Name of the field
            value: Extracted value
            confidence: Confidence score (0.0 to 1.0)
        """
        payload = {'value': value, 'confidence': confidence}
        if provenance is not None:
            payload['provenance'] = provenance
        self.fields[field_name] = payload
    
    def get_field(self, field_name: str, default: Any = None) -> Any:
        """
        Get a field value by name.
        
        Args:
            field_name: Name of the field to get
            default: Default value if field doesn't exist
            
        Returns:
            The field value or default if not found
        """
        if field_name in self.fields:
            return self.fields[field_name].get('value', default)
        return default
    
    def has_field(self, field_name: str) -> bool:
        """Check if a field exists in the context."""
        return field_name in self.fields

    @property
    def ocr_quality(self) -> float:
        """Compute a lightweight OCR quality proxy from raw_lines (0.0-1.0). Cached."""
        if self._ocr_quality is not None:
            return self._ocr_quality
        lines = self.raw_lines or []
        if not lines:
            self._ocr_quality = 0.0
            return self._ocr_quality
        # Features: average token length, vowel ratio, non-alnum ratio, line diversity
        tokens = [t for line in lines for t in line.split()]
        if not tokens:
            self._ocr_quality = 0.0
            return self._ocr_quality
        avg_len = sum(len(t) for t in tokens) / max(1, len(tokens))
        vowels = sum(len(re.findall(r"[aeiouAEIOU]", t)) for t in tokens)
        vowel_ratio = vowels / max(1, sum(len(t) for t in tokens))
        non_alnum = sum(len(re.findall(r"[^0-9A-Za-z]", t)) for t in tokens)
        non_alnum_ratio = non_alnum / max(1, sum(len(t) for t in tokens))
        unique_lines = len(set([l.strip() for l in lines if l.strip()]))
        diversity = unique_lines / max(1, len(lines))
        # Heuristic scoring
        score = 0.0
        # Favor moderate token length (3-12)
        score += max(0.0, 1.0 - abs(avg_len - 6) / 6) * 0.3
        # Favor vowel presence 20%-60%
        score += max(0.0, 1.0 - abs(vowel_ratio - 0.35) / 0.35) * 0.3
        # Penalize non-alnum ratio
        score += max(0.0, 1.0 - non_alnum_ratio * 3.0) * 0.2
        # Favor diversity
        score += diversity * 0.2
        self._ocr_quality = max(0.0, min(1.0, score))
        return self._ocr_quality

# ----------------------------
# Lightweight output schemas
# ----------------------------

# Expected field keys (informational; parsers may return subsets with confidence)
SIM_FIELDS: List[str] = [
    "sim_number", "name", "date_of_birth", "address", "class", "valid_from", "valid_to", "blood_type",
]

STNK_FIELDS: List[str] = [
    "plate_number", "owner_name", "address", "brand", "model", "year", "vin_chassis", "engine_number", "tax_valid_to",
]

KIR_FIELDS: List[str] = [
    "certificate_number", "vehicle_id", "inspection_date", "valid_until", "issuer",
]

def make_document_result(document_type: str, fields: Optional[Dict[str, Any]] = None,
                         confidence: float = 0.0, provenance: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize parsed document result shape across parsers."""
    payload: Dict[str, Any] = {
        "document_type": document_type,
        "fields": fields or {},
        "confidence": float(max(0.0, min(1.0, confidence))),
    }
    if provenance is not None:
        payload["provenance"] = provenance
    return payload