"""
Kewarganegaraan Extractor for Indonesian ID Card (KTP) OCR processing.

This module provides the KewarganegaraanExtractor class which is responsible for extracting
the citizenship (kewarganegaraan) information from Indonesian ID cards.
"""

import re
import logging
from typing import Dict, List, Optional, Pattern, Set, Tuple

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class KewarganegaraanExtractor(FieldExtractor):
    """Extracts citizenship (kewarganegaraan) from KTP text."""
    
    def __init__(self):
        super().__init__('kewarganegaraan')
        
        # Valid citizenship values with common OCR errors
        self.valid_citizenships: Set[str] = {
            'WNI', 'WARGA NEGARA INDONESIA', 'INDONESIA', 'INDONESIAN',
            'WNA', 'WARGA NEGARA ASING', 'ASING', 'FOREIGN',
            # Common OCR errors
            'WNI', 'WNI', 'WNI', 'WNI', 'WNI',
            'WARGA NEGARA INDONESIA', 'WARGA NEGARA INDONESIA',
            'WARGA NEGARA INDONESIA', 'WARGA NEGARA INDONESIA',
            'INDONESIA', 'INDONESIA', 'INDONESIA', 'INDONESIA',
            'WNA', 'WNA', 'WNA', 'WNA', 'WNA',
            'WARGA NEGARA ASING', 'WARGA NEGARA ASING',
            'WARGA NEGARA ASING', 'WARGA NEGARA ASING',
            'ASING', 'ASING', 'ASING', 'ASING',
        }
        
        # Mapping of variations to standard values
        self.citizenship_mapping: Dict[str, str] = {
            # WNI variations
            'WNI': 'WNI',
            'WARGA NEGARA INDONESIA': 'WNI',
            'INDONESIA': 'WNI',
            'INDONESIAN': 'WNI',
            'WNI': 'WNI',
            'WNI': 'WNI',
            'WNI': 'WNI',
            'WNI': 'WNI',
            'WNI': 'WNI',
            
            # WNA variations
            'WNA': 'WNA',
            'WARGA NEGARA ASING': 'WNA',
            'ASING': 'WNA',
            'FOREIGN': 'WNA',
            'WNA': 'WNA',
            'WNA': 'WNA',
            'WNA': 'WNA',
            'WNA': 'WNA',
            'WNA': 'WNA',
        }
        
        # Patterns to identify the kewarganegaraan label
        self.label_patterns: List[Tuple[Pattern, int]] = [
            # Format: (pattern, group containing the value)
            (re.compile(r'KEWARGANEGARAAN[\s:]*([A-Za-z\s]+)'), 1),
            (re.compile(r'KEWARGANEGARAAN[\s:]'), 0),
            (re.compile(r'KEWARGANEGARAAN'), 0),
            (re.compile(r'KEWARGANEGARAAN'), 0),
            (re.compile(r'KEWARGANEGARAAN'), 0),
            (re.compile(r'KEWARGANEGARAAN'), 0),
            (re.compile(r'KEWARGANEGARAAN'), 0),
        ]
        
        # Common false positives to skip
        self.skip_terms: List[str] = [
            'nik', 'nama', 'tempat', 'lahir', 'jenis', 'kelamin', 'gol', 'darah',
            'rt/rw', 'rt rw', 'kel/desa', 'kecamatan', 'agama', 'pekerjaan',
            'status', 'perkawinan', 'berlaku', 'hingga', 'alamat', 'nama',
            'kota', 'kabupaten', 'kecamatan', 'kelurahan', 'desa', 'kode pos',
            'provinsi', 'kab', 'kec', 'kel', 'kode', 'pos', 'rt', 'rw'
        ]
        
        # Maximum lines to check after finding a label
        self.max_lines_to_check: int = 2
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract citizenship from the document.
        
        Args:
            context: ParserContext containing the document lines
            
        Returns:
            Extracted citizenship (WNI or WNA) or None if not found
        """
        # Try to extract by label patterns first (more reliable).
        # Uppercase before matching: label patterns are uppercase and OCR
        # may return mixed case ("Kewarganegaraan: ...").
        for i, line in enumerate(context.raw_lines):
            line = line.strip().upper()
            if not line or self._is_likely_false_positive(line):
                continue

            # Check for label patterns
            for pattern, group_idx in self.label_patterns:
                match = pattern.search(line)
                if match:
                    self._log_debug(context, "Found kewarganegaraan label",
                                  pattern=pattern.pattern, line_number=i)
                    
                    # Try to extract citizenship from the same line after the label
                    citizenship = self._extract_after_label(line, pattern, group_idx, context)
                    if citizenship:
                        return citizenship
                    
                    # If not found in the same line, check the next few lines
                    citizenship = self._extract_in_following_lines(context, i)
                    if citizenship:
                        return citizenship
        
        # If not found by label, try to find a standalone citizenship
        return self._find_standalone_citizenship(context)
    
    def _extract_after_label(self, line: str, pattern: Pattern, group_idx: int,
                           context: ParserContext) -> Optional[str]:
        """Extract citizenship from the same line as the label."""
        match = pattern.search(line)
        if not match:
            return None
            
        # If group_idx is 0, the pattern didn't capture the value
        if group_idx == 0:
            # Get the text after the match
            text_after = line[match.end():].strip()
            if not text_after:
                return None
                
            # Try to extract citizenship from the text after the label
            return self._normalize_citizenship(text_after, context)
        
        # If group_idx > 0, use the captured group
        if match.group(group_idx):
            return self._normalize_citizenship(match.group(group_idx), context)
            
        return None
    
    def _extract_in_following_lines(self, context: ParserContext, 
                                  start_line: int) -> Optional[str]:
        """Extract citizenship from lines following a label."""
        end_line = min(start_line + self.max_lines_to_check + 1, len(context.raw_lines))
        
        for i in range(start_line + 1, end_line):
            line = context.raw_lines[i].strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Try to extract citizenship from the line
            citizenship = self._normalize_citizenship(line, context)
            if citizenship:
                return citizenship
                
        return None
    
    def _find_standalone_citizenship(self, context: ParserContext) -> Optional[str]:
        """Try to find a standalone citizenship in the document."""
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Skip lines that are too long (unlikely to be just a citizenship)
            if len(line) > 30:
                continue
                
            # Try to extract citizenship from the line
            citizenship = self._normalize_citizenship(line, context)
            if citizenship:
                self._log_info(context, "Found standalone citizenship",
                             line_number=i, citizenship=citizenship)
                return citizenship
                
        return None
    
    def _normalize_citizenship(self, text: str, 
                             context: Optional[ParserContext] = None) -> Optional[str]:
        """Normalize citizenship text to standard format.
        
        Args:
            text: The text to normalize
            context: Optional ParserContext for logging
            
        Returns:
            Normalized citizenship (WNI or WNA) or None if invalid
        """
        if not text or not text.strip():
            return None
            
        # Clean and standardize the input
        text = text.upper().strip()
        
        # Remove common prefixes/suffixes
        text = re.sub(r'^[^A-Z0-9]+', '', text)  # Remove non-alphanumeric from start
        text = re.sub(r'[^A-Z0-9]+$', '', text)  # Remove non-alphanumeric from end
        
        # Check if it's a valid citizenship
        if text in self.valid_citizenships:
            return self.citizenship_mapping.get(text, text)
            
        # Check if it's in the mapping
        if text in self.citizenship_mapping:
            return self.citizenship_mapping[text]
            
        # Try to match the beginning of the text
        for citizenship in self.valid_citizenships:
            if text.startswith(citizenship) or citizenship.startswith(text):
                return self.citizenship_mapping.get(citizenship, citizenship)
                
        # Try to match any part of the text
        for citizenship in self.valid_citizenships:
            if citizenship in text:
                return self.citizenship_mapping.get(citizenship, citizenship)

        # Last resort for 3-letter tokens where fuzzy ratios are too coarse:
        # WN + one OCR-confused char (WNl/WN1/WN| -> WNI, WN4 -> WNA)
        m = re.fullmatch(r"WN([A-Z0-9|!])", text)
        if m:
            ch = m.group(1)
            if ch in "I1L|!J":
                return "WNI"
            if ch in "A4":
                return "WNA"

        return None
    
    def _is_likely_false_positive(self, text: str) -> bool:
        """Check if the text is likely a false positive for a citizenship."""
        if not text:
            return True
            
        text_lower = text.lower()
        
        # Skip lines that contain other field labels
        if any(term in text_lower for term in self.skip_terms):
            return True
            
        # Skip lines that are too long (unlikely to be just a citizenship)
        if len(text) > 30:
            return True
            
        # Skip lines that look like NIK or other numeric IDs
        if re.match(r'^\d+$', text.replace(' ', '')):
            return True
            
        return False
