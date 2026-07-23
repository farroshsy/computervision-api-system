"""
Status Perkawinan Extractor for Indonesian ID Card (KTP) OCR processing.

This module provides the StatusPerkawinanExtractor class which is responsible for extracting
the marital status (status perkawinan) information from Indonesian ID cards.
"""

import re
import logging
from typing import Dict, List, Optional, Pattern, Set, Tuple

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class StatusPerkawinanExtractor(FieldExtractor):
    """Extracts marital status (status perkawinan) from KTP text."""
    
    def __init__(self):
        super().__init__('status_perkawinan')
        
        # Valid marital status values with common OCR errors
        self.valid_statuses: Set[str] = {
            'BELUM KAWIN', 'KAWIN', 'CERAI HIDUP', 'CERAI MATI',
            # Common OCR errors
            'BELUM KAWIN', 'BELUM KAWIN', 'BELUM KAWIN', 'BELUM KAWIN',
            'KAWIN', 'KAWIN', 'KAWIN', 'KAWIN',
            'CERAI HIDUP', 'CERAI HIDUP', 'CERAI HIDUP', 'CERAI HIDUP',
            'CERAI MATI', 'CERAI MATI', 'CERAI MATI', 'CERAI MATI'
        }
        
        # Mapping of variations to standard values
        self.status_mapping: Dict[str, str] = {
            # Belum Kawin variations
            'BELUM KAWIN': 'BELUM KAWIN',
            'BELUM KAWIN': 'BELUM KAWIN',
            'BELUM KAWIN': 'BELUM KAWIN',
            'BELUM KAWIN': 'BELUM KAWIN',
            'BELUM NIKAH': 'BELUM KAWIN',
            'BELUM': 'BELUM KAWIN',
            'SINGLE': 'BELUM KAWIN',
            'LAJANG': 'BELUM KAWIN',
            'BELUM KAWIN': 'BELUM KAWIN',
            
            # Kawin variations
            'KAWIN': 'KAWIN',
            'KAWIN': 'KAWIN',
            'KAWIN': 'KAWIN',
            'KAWIN': 'KAWIN',
            'MENIKAH': 'KAWIN',
            'SUDAH MENIKAH': 'KAWIN',
            'SUDAH KAWIN': 'KAWIN',
            'KAWIN': 'KAWIN',
            'KAWIN': 'KAWIN',
            
            # Cerai Hidup variations
            'CERAI HIDUP': 'CERAI HIDUP',
            'CERAI HIDUP': 'CERAI HIDUP',
            'CERAI HIDUP': 'CERAI HIDUP',
            'CERAI HIDUP': 'CERAI HIDUP',
            'CERAI': 'CERAI HIDUP',
            'BERCERAI HIDUP': 'CERAI HIDUP',
            'CERAI HIDUP': 'CERAI HIDUP',
            'CERAI HIDUP': 'CERAI HIDUP',
            'CERAI HIDUP': 'CERAI HIDUP',
            
            # Cerai Mati variations
            'CERAI MATI': 'CERAI MATI',
            'CERAI MATI': 'CERAI MATI',
            'CERAI MATI': 'CERAI MATI',
            'CERAI MATI': 'CERAI MATI',
            'MENINGGAL': 'CERAI MATI',
            'JANDA': 'CERAI MATI',
            'DUDA': 'CERAI MATI',
            'CERAI MATI': 'CERAI MATI',
            'CERAI MATI': 'CERAI MATI'
        }
        
        # Patterns to identify the status perkawinan label
        self.label_patterns: List[Tuple[Pattern, int]] = [
            # Format: (pattern, group containing the value)
            (re.compile(r'STATUS[\s:]*PERKAWINAN[\s:]*([A-Za-z\s]+)'), 1),
            (re.compile(r'STATUS[\s:]*PERKAWINAN'), 0),
            (re.compile(r'STATUS[\s:]*PERKAWINAN'), 0),
            (re.compile(r'STATUS[\s:]*PERKAWINAN'), 0),
            (re.compile(r'STATUS[\s:]*PERKAWINAN'), 0),
            (re.compile(r'STATUS[\s:]*PERKAWINAN'), 0),
            (re.compile(r'STATUS[\s:]*PERKAWINAN'), 0),
        ]
        
        # Common false positives to skip
        self.skip_terms: List[str] = [
            'nik', 'nama', 'tempat', 'lahir', 'jenis', 'kelamin', 'gol', 'darah',
            'rt/rw', 'rt rw', 'kel/desa', 'kecamatan', 'agama', 'pekerjaan',
            'kewarganegaraan', 'berlaku', 'hingga'
        ]
        
        # Maximum lines to check after finding a label
        self.max_lines_to_check: int = 2
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract marital status from the document.
        
        Args:
            context: ParserContext containing the document lines
            
        Returns:
            Extracted marital status or None if not found
        """
        # Try to extract by label patterns first (more reliable)
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Check for label patterns
            for pattern, group_idx in self.label_patterns:
                match = pattern.search(line)
                if match:
                    self._log_debug(context, "Found status perkawinan label", 
                                  pattern=pattern.pattern, line_number=i)
                    
                    # Try to extract status from the same line after the label
                    status = self._extract_after_label(line, pattern, group_idx, context)
                    if status:
                        return status
                    
                    # If not found in the same line, check the next few lines
                    status = self._extract_in_following_lines(context, i)
                    if status:
                        return status
        
        # If not found by label, try to find a standalone status
        return self._find_standalone_status(context)
    
    def _extract_after_label(self, line: str, pattern: Pattern, group_idx: int,
                           context: ParserContext) -> Optional[str]:
        """Extract status from the same line as the label."""
        match = pattern.search(line)
        if not match:
            return None
            
        # If group_idx is 0, the pattern didn't capture the value
        if group_idx == 0:
            # Get the text after the match
            text_after = line[match.end():].strip()
            if not text_after:
                return None
                
            # Try to extract status from the text after the label
            return self._normalize_status(text_after, context)
        
        # If group_idx > 0, use the captured group
        if match.group(group_idx):
            return self._normalize_status(match.group(group_idx), context)
            
        return None
    
    def _extract_in_following_lines(self, context: ParserContext, 
                                  start_line: int) -> Optional[str]:
        """Extract status from lines following a label."""
        end_line = min(start_line + self.max_lines_to_check + 1, len(context.raw_lines))
        
        for i in range(start_line + 1, end_line):
            line = context.raw_lines[i].strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Try to extract status from the line
            status = self._normalize_status(line, context)
            if status:
                return status
                
        return None
    
    def _find_standalone_status(self, context: ParserContext) -> Optional[str]:
        """Try to find a standalone status in the document."""
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Skip lines that are too long (unlikely to be just a status)
            if len(line) > 30:
                continue
                
            # Try to extract status from the line
            status = self._normalize_status(line, context)
            if status:
                self._log_info(context, "Found standalone status",
                             line_number=i, status=status)
                return status
                
        return None
    
    def _normalize_status(self, text: str, 
                         context: Optional[ParserContext] = None) -> Optional[str]:
        """Normalize status text to standard format.
        
        Args:
            text: The text to normalize
            context: Optional ParserContext for logging
            
        Returns:
            Normalized status or None if invalid
        """
        if not text or not text.strip():
            return None
            
        # Clean and standardize the input
        text = text.upper().strip()
        
        # Remove common prefixes/suffixes
        text = re.sub(r'^[^A-Z0-9]+', '', text)  # Remove non-alphanumeric from start
        text = re.sub(r'[^A-Z0-9]+$', '', text)  # Remove non-alphanumeric from end
        
        # Check if it's a valid status
        if text in self.valid_statuses:
            return self.status_mapping.get(text, text)
            
        # Check if it's in the mapping
        if text in self.status_mapping:
            return self.status_mapping[text]
            
        # Try to match the beginning of the text
        for status in self.valid_statuses:
            if text.startswith(status) or status.startswith(text):
                return self.status_mapping.get(status, status)
                
        # Try to match any part of the text
        for status in self.valid_statuses:
            if status in text:
                return self.status_mapping.get(status, status)
                
        return None
    
    def _is_likely_false_positive(self, text: str) -> bool:
        """Check if the text is likely a false positive for a status."""
        if not text:
            return True
            
        text_lower = text.lower()
        
        # Skip lines that contain other field labels
        if any(term in text_lower for term in self.skip_terms):
            return True
            
        # Skip lines that are too long (unlikely to be just a status)
        if len(text) > 50:
            return True
            
        # Skip lines that look like NIK or other numeric IDs
        if re.match(r'^\d+$', text.replace(' ', '')):
            return True
            
        return False
