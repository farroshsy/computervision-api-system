"""
Jenis Kelamin Extractor for Indonesian ID Card (KTP) OCR processing.

This module provides the JenisKelaminExtractor class which is responsible for extracting
the gender (jenis kelamin) information from Indonesian ID cards.
"""

import re
import logging
from typing import Dict, List, Optional, Pattern, Set, Tuple

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class JenisKelaminExtractor(FieldExtractor):
    """Extracts gender (jenis kelamin) from KTP text."""
    
    def __init__(self):
        super().__init__('jenis_kelamin')
        
        # Valid gender values with common OCR errors
        self.valid_genders: Set[str] = {
            'LAKI-LAKI', 'LAKI LAKI', 'LAKILAKI', 'L', 'LAKI',
            'PEREMPUAN', 'PEREMPN', 'PEREMP', 'P', 'PER',
            # Common OCR errors
            'LAK1-LAK1', 'LAK1 LAK1', 'LAK1LAK1',
            'PEREMP0AN', 'PEREMP0N', 'PEREMPOAN', 'PEREMPU4N',
            'LAKILAK', 'LAKILAKI', 'LAKILAK1', 'LAKILAKI',
            'PEREMPUAN', 'PEREMPUAN', 'PEREMPUAN', 'PEREMPUAN'
        }
        
        # Mapping of variations to standard values
        self.gender_mapping: Dict[str, str] = {
            # Male variations
            'LAKI-LAKI': 'LAKI-LAKI',
            'LAKI LAKI': 'LAKI-LAKI',
            'LAKILAKI': 'LAKI-LAKI',
            'L': 'LAKI-LAKI',
            'LAKI': 'LAKI-LAKI',
            'LAK1-LAK1': 'LAKI-LAKI',
            'LAK1 LAK1': 'LAKI-LAKI',
            'LAK1LAK1': 'LAKI-LAKI',
            'LAKILAK': 'LAKI-LAKI',
            'LAKILAKI': 'LAKI-LAKI',
            'LAKILAK1': 'LAKI-LAKI',
            
            # Female variations
            'PEREMPUAN': 'PEREMPUAN',
            'PEREMPN': 'PEREMPUAN',
            'PEREMP': 'PEREMPUAN',
            'P': 'PEREMPUAN',
            'PER': 'PEREMPUAN',
            'PEREMP0AN': 'PEREMPUAN',
            'PEREMP0N': 'PEREMPUAN',
            'PEREMPOAN': 'PEREMPUAN',
            'PEREMPU4N': 'PEREMPUAN',
            'WANITA': 'PEREMPUAN',
            'PEREMPUAN': 'PEREMPUAN',
            'PEREMPUAN': 'PEREMPUAN',
            'PEREMPUAN': 'PEREMPUAN'
        }
        
        # Patterns to identify the jenis kelamin label
        self.label_patterns: List[Tuple[Pattern, int]] = [
            # Format: (pattern, group containing the value)
            (re.compile(r'JENIS[\s:]*KELAMIN[\s:]*([A-Za-z0-9\-\s]+)', re.IGNORECASE), 1),
            (re.compile(r'JENIS[\s:]*KELAMIN', re.IGNORECASE), 0),
            (re.compile(r'JK[\s:]*([A-Za-z0-9\-\s]+)', re.IGNORECASE), 1),
            (re.compile(r'JK', re.IGNORECASE), 0),
            (re.compile(r'JENIS[\s:]*KEL', re.IGNORECASE), 0),
            (re.compile(r'JENKEL[\s:]*([A-Za-z0-9\-\s]+)', re.IGNORECASE), 1),
            (re.compile(r'JENKEL', re.IGNORECASE), 0),
            (re.compile(r'KELAMIN[\s:]*([A-Za-z0-9\-\s]+)', re.IGNORECASE), 1),
            (re.compile(r'KELAMIN', re.IGNORECASE), 0),
        ]
        
        # Common false positives to skip
        self.skip_terms: List[str] = [
            'nik', 'nama', 'tempat', 'lahir', 'gol', 'darah',
            'rt/rw', 'rt rw', 'kel/desa', 'kecamatan', 'agama', 'pekerjaan',
            'status', 'perkawinan', 'kewarganegaraan', 'berlaku', 'hingga'
        ]
        
        # Maximum lines to check after finding a label
        self.max_lines_to_check: int = 2
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract gender from the document.
        
        Args:
            context: ParserContext containing the document lines
            
        Returns:
            Extracted gender (LAKI-LAKI or PEREMPUAN) or None if not found
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
                    self._log_debug(context, "Found jenis kelamin label", 
                                  pattern=pattern.pattern, line_number=i)
                    
                    # Try to extract gender from the same line after the label
                    gender = self._extract_after_label(line, pattern, group_idx, context)
                    if gender:
                        return gender
                    
                    # If not found in the same line, check the next few lines
                    gender = self._extract_in_following_lines(context, i)
                    if gender:
                        return gender
        
        # If not found by label, try to find a standalone gender
        return self._find_standalone_gender(context)
    
    def _extract_after_label(self, line: str, pattern: Pattern, group_idx: int,
                           context: ParserContext) -> Optional[str]:
        """Extract gender from the same line as the label."""
        match = pattern.search(line)
        if not match:
            return None
            
        # If group_idx is 0, the pattern didn't capture the value
        if group_idx == 0:
            # Get the text after the match
            text_after = line[match.end():].strip()
            if not text_after:
                return None
                
            # Try to extract gender from the text after the label
            return self._normalize_gender(text_after, context)
        
        # If group_idx > 0, use the captured group
        if match.group(group_idx):
            return self._normalize_gender(match.group(group_idx), context)
            
        return None
    
    def _extract_in_following_lines(self, context: ParserContext, 
                                  start_line: int) -> Optional[str]:
        """Extract gender from lines following a label."""
        end_line = min(start_line + self.max_lines_to_check + 1, len(context.raw_lines))
        
        for i in range(start_line + 1, end_line):
            line = context.raw_lines[i].strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Try to extract gender from the line
            gender = self._normalize_gender(line, context)
            if gender:
                return gender
                
        return None
    
    def _find_standalone_gender(self, context: ParserContext) -> Optional[str]:
        """Try to find a standalone gender in the document."""
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Skip lines that are too long (unlikely to be just a gender)
            if len(line) > 20:
                continue

            # Single-letter forms (P/L/PER/LK) are only trustworthy right
            # after a label; standalone they match random OCR fragments
            if len(line.strip()) <= 3:
                continue

            # Try to extract gender from the line
            gender = self._normalize_gender(line, context)
            if gender:
                self._log_info(context, "Found standalone gender",
                             line_number=i, gender=gender)
                return gender
                
        return None
    
    def _normalize_gender(self, text: str, 
                         context: Optional[ParserContext] = None) -> Optional[str]:
        """Normalize gender text to standard format.
        
        Args:
            text: The text to normalize
            context: Optional ParserContext for logging
            
        Returns:
            Normalized gender (LAKI-LAKI or PEREMPUAN) or None if invalid
        """
        if not text or not text.strip():
            return None
            
        # Clean and standardize the input
        text = text.upper().strip()
        # Normalize unicode dashes to '-' and collapse multiple spaces
        text = text.replace('\u2013', '-').replace('\u2014', '-')
        text = re.sub(r'\s+', ' ', text)
        # Remove common prefixes/suffixes
        text = re.sub(r'^[^A-Z0-9]+', '', text)  # Remove non-alphanumeric from start
        text = re.sub(r'[^A-Z0-9]+$', '', text)  # Remove non-alphanumeric from end
        # Also try a hyphen-normalized variant (e.g., "LAKI LAKI" -> "LAKI-LAKI")
        hyphen_norm = text.replace(' ', '-')
        
        # Check if it's a valid gender
        if text in self.valid_genders:
            return self.gender_mapping.get(text, text)
        if hyphen_norm in self.valid_genders:
            return self.gender_mapping.get(hyphen_norm, hyphen_norm)
            
        # Check if it's in the mapping
        if text in self.gender_mapping:
            return self.gender_mapping[text]
        if hyphen_norm in self.gender_mapping:
            return self.gender_mapping[hyphen_norm]
            
        # Try to match the beginning of the text. Only for tokens >= 4 chars:
        # short tokens (P, L, PER, LK) make startswith match any word with
        # that initial (e.g. "PROVINSI..." -> PEREMPUAN) and are already
        # handled by the exact-match mapping above.
        for gender in self.valid_genders:
            if len(gender) < 4 or len(text) < 4:
                continue
            if text.startswith(gender) or gender.startswith(text):
                return self.gender_mapping.get(gender, gender)
                
        # Try to match any part of the text
        for gender in self.valid_genders:
            if len(gender) >= 4 and gender in text:
                return self.gender_mapping.get(gender, gender)

        return None
    
    def _is_likely_false_positive(self, text: str) -> bool:
        """Check if the text is likely a false positive for a gender."""
        if not text:
            return True
            
        text_lower = text.lower()
        
        # Skip lines that contain other field labels
        if any(term in text_lower for term in self.skip_terms):
            return True
            
        # Skip lines that are too long (unlikely to be just a gender)
        if len(text) > 30:
            return True
            
        # Skip lines that look like NIK or other numeric IDs
        if re.match(r'^\d+$', text.replace(' ', '')):
            return True
            
        return False
