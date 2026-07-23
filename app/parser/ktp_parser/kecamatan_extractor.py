"""
Kecamatan Extractor for Indonesian ID Card (KTP) OCR processing.

This module provides the KecamatanExtractor class which is responsible for extracting
the sub-district (kecamatan) information from Indonesian ID cards.
"""

import re
import logging
from typing import Dict, List, Optional, Pattern, Set, Tuple

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class KecamatanExtractor(FieldExtractor):
    """Extracts sub-district (kecamatan) from KTP text."""
    
    def __init__(self):
        super().__init__('kecamatan')
        
        # Patterns to identify the kecamatan label
        self.label_patterns: List[Tuple[Pattern, int]] = [
            # Format: (pattern, group containing the value)
            (re.compile(r'KEC[\s\.:]+([^\n]+)'), 1),  # KEC. or KEC:
            (re.compile(r'KECAMATAN[\s:]+([^\n]+)'), 1),  # KECAMATAN:
            (re.compile(r'(?<![A-Za-z])(?:KEC\.?|KECAMATAN)[\s:.]*'), 0),  # Just the label
        ]
        
        # Common false positives to skip
        self.skip_terms: List[str] = [
            'nik', 'nama', 'tempat', 'lahir', 'jenis', 'kelamin', 'gol', 'darah',
            'rt/rw', 'rt rw', 'kel/desa', 'kecamatan', 'agama', 'pekerjaan',
            'status', 'perkawinan', 'berlaku', 'hingga', 'alamat', 'nama',
            'kota', 'kabupaten', 'kota', 'kelurahan', 'desa', 'kode pos',
            'provinsi', 'kab', 'kec', 'kel', 'kode', 'pos', 'rt', 'rw',
            'kewarganegaraan', 'pekerjaan', 'agama'
        ]

        # Administrative header terms that should never be taken as kecamatan values
        self.admin_header_terms: List[str] = [
            'prov', 'provinsi', 'kab', 'kabupaten', 'kota', 'kotamadya', 'kodya', 'kodya'
        ]
        
        # Maximum lines to check after finding a label
        self.max_lines_to_check: int = 2
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract kecamatan from the document.
        
        Args:
            context: ParserContext containing the document lines
            
        Returns:
            Extracted kecamatan or None if not found
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
                    self._log_debug(context, "Found kecamatan label", 
                                  pattern=pattern.pattern, line_number=i)
                    
                    # Try to extract kecamatan from the same line after the label
                    kecamatan = self._extract_after_label(line, pattern, group_idx, context)
                    if kecamatan:
                        return kecamatan
                    
                    # If not found in the same line, check the next few lines
                    kecamatan = self._extract_in_following_lines(context, i)
                    if kecamatan:
                        return kecamatan
        
        # If not found by label, do not guess: return None to avoid header/name misclassification
        self._log_info(context, "Kecamatan not found via label; skipping standalone guess to avoid false positives")
        return None
    
    def _extract_after_label(self, line: str, pattern: Pattern, group_idx: int,
                           context: ParserContext) -> Optional[str]:
        """Extract kecamatan from the same line as the label."""
        match = pattern.search(line)
        if not match:
            return None
            
        # If group_idx is 0, the pattern didn't capture the value
        if group_idx == 0:
            # Get the text after the match
            text_after = line[match.end():].strip()
            if not text_after:
                return None
                
            # Try to extract kecamatan from the text after the label
            return self._normalize_kecamatan(text_after, context)
        
        # If group_idx > 0, use the captured group
        if match.group(group_idx):
            return self._normalize_kecamatan(match.group(group_idx), context)
            
        return None
    
    def _extract_in_following_lines(self, context: ParserContext, 
                                  start_line: int) -> Optional[str]:
        """Extract kecamatan from lines following a label."""
        end_line = min(start_line + self.max_lines_to_check + 1, len(context.raw_lines))
        
        for i in range(start_line + 1, end_line):
            line = context.raw_lines[i].strip()
            if not line or self._is_likely_false_positive(line):
                continue
            # Skip administrative header-like lines
            if self._is_admin_header(line):
                continue
            
            # Try to extract kecamatan from the line
            kecamatan = self._normalize_kecamatan(line, context)
            if kecamatan:
                return kecamatan
                
        return None
    
    # Standalone kecamatan detection disabled intentionally to reduce false positives
    
    def _normalize_kecamatan(self, text: str, 
                           context: Optional[ParserContext] = None) -> Optional[str]:
        """Normalize kecamatan text.
        
        Args:
            text: The text to normalize
            context: Optional ParserContext for logging
            
        Returns:
            Normalized kecamatan or None if invalid
        """
        if not text or not text.strip():
            return None
            
        # Clean and standardize the input
        text = text.strip()
        # Quick reject if contains admin header terms
        low = text.lower()
        if any(term in low for term in self.admin_header_terms):
            return None
        
        # Remove common prefixes/suffixes
        text = re.sub(r'^[^A-Za-z]+', '', text)  # Remove non-alphabetic from start
        text = re.sub(r'[^A-Za-z\s]+$', '', text)  # Remove non-alphabetic from end
        text = text.strip()
        
        # Skip if too short or too long
        if len(text) < 3 or len(text) > 50:
            return None
            
        # Skip if it's just a number or contains digits (unlikely to be a kecamatan)
        if re.search(r'\d', text):
            return None
            
        # Title case the text
        text = text.title()
        
        return text if text else None

    def _is_admin_header(self, text: str) -> bool:
        """Detects lines that look like administrative headers (PROVINSI/KABUPATEN/KOTA)."""
        t = text.strip().lower()
        if any(term in t for term in self.admin_header_terms):
            # Stronger check: starts with these admin keywords
            return bool(re.match(r'^(prov(\.|insi)?|kab(\.|upaten)?|kota)\b', t))
        return False
    
    def _is_likely_false_positive(self, text: str) -> bool:
        """Check if the text is likely a false positive for a kecamatan."""
        if not text:
            return True
            
        text_lower = text.lower()
        
        # Skip lines that contain other field labels
        if any(term in text_lower for term in self.skip_terms):
            return True
        # Skip admin headers
        if self._is_admin_header(text):
            return True
            
        # Skip lines that are too long (unlikely to be just a kecamatan)
        if len(text) > 50:
            return True
            
        # Skip lines that look like NIK or other numeric IDs
        if re.match(r'^\d+$', text.replace(' ', '')):
            return True
            
        # Skip lines that don't contain any letters
        if not re.search(r'[A-Za-z]', text):
            return True
            
        return False
