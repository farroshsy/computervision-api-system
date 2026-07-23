"""
RT/RW Extractor for Indonesian ID Card (KTP) OCR processing.

This module provides the RtRwExtractor class which is responsible for extracting
RT (Rukun Tetangga) and RW (Rukun Warga) information from Indonesian ID cards.
RT/RW are neighborhood administrative divisions in Indonesia.
"""

import re
import logging
from typing import Dict, List, Optional, Tuple, Any

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class RtRwExtractor(FieldExtractor):
    """Extracts RT/RW (neighborhood) information from KTP text."""
    
    def __init__(self):
        super().__init__('rt_rw')
        self.label_patterns = [
            # Standard format with variations
            r'RT[/\s]?RW\s*[:.]?\s*([\d/\\\s]+\d+)',  # RT/RW: 001/002
            r'RT[/\s]?RW\s*[:.]?\s*([\d/\\\s]+)',      # RT/RW: 001/002 with spaces
            r'RT[^\w]?RW\s*[:.]?\s*([\d/\\\s]+)',     # RT-RW: 001/002 or RT.RW: 001/002
            r'RT\s*[/\\-]?\s*RW?\s*[:.]?\s*([\d/\\\s]+)',  # RT / RW: 001/002
            # Patterns without capture groups - will use remaining text
            r'RT[/\s]?RW\s*[:.]?',
            r'RT[^\w]?RW\s*[:.]?',
            r'RT\s*[/\\-]?\s*RW?\b',
            # Just RT/RW label
            r'RT[/\\]?RW',
            # Common OCR errors in label
            r'RT[^\w]?RW',  # RT-RW, RT.RW, RT RW, etc.
            r'RT[^\w]?RW?',  # RT-R, RT R, etc.
        ]
        self.skip_terms = [
            'nik', 'nama', 'tempat', 'lahir', 'jenis', 'kelamin', 'gol', 'darah',
            'kel/desa', 'kecamatan', 'agama', 'pekerjaan', 'status', 'perkawinan',
            'kewarganegaraan', 'berlaku', 'hingga', 'masa berlaku', 'jenis kelamin',
            'tempat/tgl', 'terpal', 'tgilahir'
        ]

    def _log_extraction(self, context: ParserContext, value: Any, **kwargs) -> Any:
        """Log the extraction and return the value.
        
        Args:
            context: The parser context
            value: The extracted value
            **kwargs: Additional context for logging
            
        Returns:
            The extracted value
        """
        self._log_info(
            context,
            f"Extracted {self.field_name}",
            value=value,
            **kwargs
        )
        return value
        
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract RT/RW information from the document.
        
        Args:
            context: ParserContext containing the document lines and extracted fields
            
        Returns:
            Formatted RT/RW string (e.g., "001/002") or None if not found
        """
        if not context or not context.raw_lines:
            return None
            
        # Try to find RT/RW by label first
        rt_rw = self._extract_by_label(context)
        if rt_rw:
            normalized = self._normalize_rt_rw(rt_rw, context)
            if normalized and self._is_valid_rt_rw(normalized):
                return self._log_extraction(
                    context, normalized,
                    line_number=0,
                    method="extract_by_label"
                )
                
        # If not found by label, try to find standalone RT/RW
        rt_rw = self._find_standalone_rt_rw(context)
        if rt_rw:
            normalized = self._normalize_rt_rw(rt_rw, context)
            if normalized and self._is_valid_rt_rw(normalized):
                return self._log_extraction(
                    context,
                    normalized,
                    line_number=0,
                    method="find_standalone_rt_rw"
                )
                
        # Removed permissive direct extraction logic to ensure only properly formatted RT/RW values are extracted
                    
        return None

    def _extract_by_label(self, context: ParserContext) -> Optional[str]:
        """Extract RT/RW when it appears with a label.
        
        Args:
            context: ParserContext with document lines
            
        Returns:
            Formatted RT/RW string or None if not found
        """
        for i, line in enumerate(context.raw_lines[:10]):  # Only check first 10 lines
            line = line.strip()
            if not line or any(term in line.lower() for term in self.skip_terms):
                continue
                
            # Check for RT/RW pattern with label
            for pattern in self.label_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if not match:
                    continue
                
                # Log the pattern that matched
                if context:
                    context.log_debug(f"Matched pattern: {pattern} on line: {line}")
                
                # Get the remaining text after the match
                remaining_text = line[match.end():].strip()
                
                # Try to extract RT/RW from the remaining text first
                if remaining_text:
                    # First, check if the remaining text contains any invalid patterns
                    # This includes things like three numbers with slashes, non-numeric characters, etc.
                    if (re.search(r'\d{1,3}\s*[/\\-]\s*\d{1,3}\s*[/\\-]\s*\d+', remaining_text) or  # 001/002/003
                        re.search(r'[^\d/\\\s-]', remaining_text) or  # Any non-digit, non-separator characters
                        re.search(r'\d{4,}', remaining_text)):  # Numbers with 4+ digits
                        return None
                        
                    # Look for RT/RW pattern in the remaining text (e.g., "RT/RW: 001/002")
                    # This pattern must match the entire remaining text to be valid
                    rt_rw_match = re.search(r'^(\d{1,3})\s*[/\\-]\s*(\d{1,3})\s*$', remaining_text)
                    if rt_rw_match:
                        rt = rt_rw_match.group(1)
                        rw = rt_rw_match.group(2)
                        # If cleaned_lines exist (stricter mode), reject labeled 1/2; else allow normalization
                        if len(rt) == 1 and len(rw) == 1:
                            if hasattr(context, 'cleaned_lines') and context.cleaned_lines:
                                return None
                        return f"{rt}/{rw}"  # Don't pad here, let _normalize_rt_rw handle validation
                    
                    # If no RT/RW pattern with separator, look for exactly two numbers separated by space
                    # But only if the entire remaining text is just those two numbers
                    numbers = re.findall(r'\b(\d{1,3})\b', remaining_text)
                    if (len(numbers) == 2 and 
                        re.fullmatch(r'\s*\d{1,3}\s+\d{1,3}\s*', remaining_text)):
                        return f"{numbers[0]}/{numbers[1]}"  # Don't pad here, let _normalize_rt_rw handle validation
                
                # If no match in remaining text, try to extract from the entire line
                # But only if there are exactly two numbers in the line
                numbers = re.findall(r'\b(\d{1,3})\b', line)
                if len(numbers) == 2:
                    full_match = re.search(r'RT[.:]?\s*RW[.:]?\s*(\d{1,3})\s*[/\\-]\s*(\d{1,3})\b', line, re.IGNORECASE)
                    if full_match:
                        rt = full_match.group(1)
                        rw = full_match.group(2)
                        if len(rt) == 1 and len(rw) == 1:
                            return None
                        return f"{rt}/{rw}"  # Don't pad here, let _normalize_rt_rw handle validation
                
                # If still no match, try the next line
                if i + 1 < len(context.raw_lines):
                    next_line = context.raw_lines[i + 1].strip()
                    if next_line and not any(term in next_line.lower() for term in self.skip_terms):
                        # Look for RT/RW pattern in the next line
                        next_match = re.search(r'(\d{1,3})\s*[/\\-]\s*(\d{1,3})', next_line)
                        if next_match:
                            rt = next_match.group(1)
                            rw = next_match.group(2)
                            if len(rt) == 1 and len(rw) == 1:
                                if hasattr(context, 'cleaned_lines') and context.cleaned_lines:
                                    return None
                            return f"{rt}/{rw}"  # Don't pad here, let _normalize_rt_rw handle validation
                        
                        # If no RT/RW pattern with separator, look for two numbers separated by space
                        numbers = re.findall(r'\b(\d{1,3})\b', next_line)
                        if len(numbers) >= 2:
                            return f"{numbers[0]}/{numbers[1]}"  # Don't pad here, let _normalize_rt_rw handle validation
        
        return None

    def _find_standalone_rt_rw(self, context: ParserContext) -> Optional[str]:
        """Find RT/RW that appears without a clear label.
        
        Args:
            context: ParserContext with document lines
            
        Returns:
            Formatted RT/RW string or None if not found
        """
        # Look for common RT/RW patterns in the document
        patterns = [
            # Standard RT/RW format with various separators (must have both RT and RW)
            r'(?:^|\s)(\d{1,3})\s*[/\\]\s*(\d{1,3})(?:\s|$)',  # 001/002 or 1/2
            r'(?:^|\s)(\d{3})\s*[/\\]\s*(\d{3})(?:\s|$)',    # 001/002 with spaces
            
            # RT/RW with labels and various separators (must have both RT and RW)
            r'(?:^|\s)RT[.:]?\s*(\d+)\s*[/\\]\s*RW[.:]?\s*(\d+)(?:\s|$)',  # RT.001/RW.002
            r'(?:^|\s)RT[.:]?\s*(\d+)\s*[/\\]\s*(\d+)(?:\s|$)',  # RT.001/002
            
            # Common OCR errors and variations (must have both RT and RW)
            r'(?:^|\s)(\d{3})[/\\](\d{3})(?:\s|$)',    # 001/002 (no space, exact 6 digits)
            r'(?:^|\s)(\d{1,3})\s*[-]\s*(\d{1,3})(?:\s|$)',  # 001-002 with dash
        ]
        
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or any(term in line.lower() for term in self.skip_terms):
                continue
                
            # First try exact patterns that require both RT and RW
            for pattern in patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match and len(match.groups()) >= 2:
                    # RT/RW format with both numbers - don't pad here, let _normalize_rt_rw handle validation
                    rt = match.group(1)
                    rw = match.group(2)
                    # If the line explicitly contains an RT/RW label and both sides are single digits, reject
                    if re.search(r'RT\s*[/\\.\-\s]*RW', line, re.IGNORECASE) and len(rt) == 1 and len(rw) == 1:
                        continue
                    
                    # Create the RT/RW string and normalize it
                    rt_rw = f"{rt}/{rw}"
                    normalized = self._normalize_rt_rw(rt_rw, context)
                    
                    # Only return if the normalized value is valid
                    if normalized and self._is_valid_rt_rw(normalized):
                        return self._log_extraction(
                            context, 
                            normalized,
                            line_number=i,
                            method=f"standalone_pattern: {pattern}"
                        )
            
            # No permissive patterns - only accept well-formatted RT/RW values
            
        # If no exact pattern matched, don't try to extract RT/RW from this line
        return None
        
        return None

    def _is_valid_rt_rw(self, value: str) -> bool:
        """Check if the extracted RT/RW value is valid.
        
        Args:
            value: The extracted RT/RW value
            
        Returns:
            bool: True if the value is a valid RT/RW format
        """
        if not value or not isinstance(value, str):
            return False
            
        # Clean the value
        value = value.upper().strip()
        
        # Check common invalid patterns
        if any(term in value.lower() for term in self.skip_terms):
            return False
            
        # Check for valid RT/RW patterns - allow 1–3 digits each side; we'll pad during normalization
        patterns = [
            r'^\d{1,3}\s*/\s*\d{1,3}$',
            r'^RT[.:]?\s*\d{1,3}\s*/\s*RW[.:]?\s*\d{1,3}$',
            r'^RT[.:]?\s*\d{1,3}\s*/\s*\d{1,3}$',
            r'^RT[.:]?\s*\d{1,3}\s*/\s*RW[.:]?\s*\d{1,3}$',
        ]
        
        # Check if any pattern matches
        if any(re.match(p, value, re.IGNORECASE) for p in patterns):
            # If we have a match, further validate the numbers
            # Extract the numbers
            numbers = re.findall(r'\d+', value)
            if len(numbers) >= 2:
                # Both RT and RW should be 1-3 digits
                rt, rw = numbers[0], numbers[1]
                return (1 <= len(rt) <= 3 and 1 <= len(rw) <= 3)
            return False
            
        return False

    def _normalize_rt_rw(self, value: str, context: Optional[ParserContext] = None) -> Optional[str]:
        """Normalize the RT/RW value to a standard format.
        
        Args:
            value: The extracted RT/RW value
            context: Optional ParserContext for logging
            
        Returns:
            Normalized RT/RW string (e.g., "001/002") or None if invalid
            
        Note:
            This method is very strict and only accepts RT/RW values that are already
            in the correct 3-digit format (e.g., "001/002"). Any other format will be rejected.
        """
        if not value or not isinstance(value, str):
            return None
            
        original_value = value
        if context:
            context.log_debug(f"Normalizing RT/RW value: {original_value}")
        
        # Accept 1–3 digits each side and pad to 3
        match = re.match(r'^\s*(\d{1,3})\s*[/\\-]\s*(\d{1,3})\s*$', value.strip())
        if match:
            rt, rw = match.groups()
            try:
                rt_num = int(rt)
                rw_num = int(rw)
                # Verify numbers are within range and not zeros-only
                if 1 <= rt_num <= 999 and 1 <= rw_num <= 999:
                    normalized = f"{str(rt_num).zfill(3)}/{str(rw_num).zfill(3)}"
                    if context:
                        context.log_debug(f"Accepted RT/RW: {original_value} -> {normalized}")
                    return normalized
            except (ValueError, TypeError):
                pass
        
        # If we get here, the format is not valid
        if context:
            context.log_debug(f"Rejected invalid RT/RW format: {original_value}")
        return None
