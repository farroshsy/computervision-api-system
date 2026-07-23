"""
Agama Extractor for Indonesian ID Card (KTP) OCR processing.

This module provides the AgamaExtractor class which is responsible for extracting
the religion (agama) information from Indonesian ID cards.
"""

import re
import logging
from typing import Dict, List, Optional, Pattern, Set, Tuple

from app.models.schemas import ParserContext
from app.utils.id_reference import AGAMA, fuzzy_correct
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class AgamaExtractor(FieldExtractor):
    """Extracts religion (agama) from KTP text."""
    
    def __init__(self):
        super().__init__('agama')
        
        # Valid religions in Indonesia with common OCR errors
        self.valid_religions: Set[str] = {
            'ISLAM', 'KRISTEN', 'KATOLIK', 'HINDU', 'BUDDHA', 'KONGHUCU',
            'KRISTEN PROTESTAN', 'PROTESTAN', 'HINDU BALI', 'BUDDHIS', 'KONGHUCU',
            # Common OCR errors
            'ISLAM', 'ISL4M', 'ISL4N', '1SLAM', 'ISLAM',
            'KRISTEN', 'KR1STEN', 'KRISTEN', 'KRISTEN', 'KRISTEN',
            'KATOLIK', 'KATOL1K', 'KATOLIK', 'KATOLIK', 'KATOLIK',
            'HINDU', 'H1NDU', 'HINDU', 'HINDU', 'HINDU',
            'BUDDHA', 'BUDDHA', 'BUDDHA', 'BUDDHA', 'BUDDHA',
            'KONGHUCU', 'KONGHUCU', 'KONGHUCU', 'KONGHUCU', 'KONGHUCU'
        }
        
        # Mapping of variations to standard values
        self.religion_mapping: Dict[str, str] = {
            # Islam
            'ISLAM': 'ISLAM',
            'ISL4M': 'ISLAM',
            'ISL4N': 'ISLAM',
            '1SLAM': 'ISLAM',
            'ISLAM': 'ISLAM',
            'MUSLIM': 'ISLAM',
            'MUSLIMIN': 'ISLAM',
            'MUSLIMAT': 'ISLAM',
            'ISLAM': 'ISLAM',
            'ISLAM': 'ISLAM',
            
            # Kristen
            'KRISTEN': 'KRISTEN',
            'KR1STEN': 'KRISTEN',
            'KRISTEN': 'KRISTEN',
            'KRISTEN': 'KRISTEN',
            'KRISTEN': 'KRISTEN',
            'KRISTEN PROTESTAN': 'KRISTEN',
            'PROTESTAN': 'KRISTEN',
            'KRISTEN': 'KRISTEN',
            'KRISTEN': 'KRISTEN',
            'KRISTEN': 'KRISTEN',
            
            # Katolik
            'KATOLIK': 'KATOLIK',
            'KATOL1K': 'KATOLIK',
            'KATOLIK': 'KATOLIK',
            'KATOLIK': 'KATOLIK',
            'KATOLIK': 'KATOLIK',
            'KATHOLIK': 'KATOLIK',
            'KATOLIK': 'KATOLIK',
            'KATOLIK': 'KATOLIK',
            'KATOLIK': 'KATOLIK',
            
            # Hindu
            'HINDU': 'HINDU',
            'H1NDU': 'HINDU',
            'HINDU': 'HINDU',
            'HINDU': 'HINDU',
            'HINDU': 'HINDU',
            'HINDU BALI': 'HINDU',
            'HINDU': 'HINDU',
            'HINDU': 'HINDU',
            'HINDU': 'HINDU',
            
            # Buddha
            'BUDDHA': 'BUDDHA',
            'BUDDHA': 'BUDDHA',
            'BUDDHA': 'BUDDHA',
            'BUDDHA': 'BUDDHA',
            'BUDDHA': 'BUDDHA',
            'BUDDHIS': 'BUDDHA',
            'BUDDHA': 'BUDDHA',
            'BUDDHA': 'BUDDHA',
            'BUDDHA': 'BUDDHA',
            
            # Konghucu
            'KONGHUCU': 'KONGHUCU',
            'KONGHUCU': 'KONGHUCU',
            'KONGHUCU': 'KONGHUCU',
            'KONGHUCU': 'KONGHUCU',
            'KONGHUCU': 'KONGHUCU',
            'KONGHUCU': 'KONGHUCU',
            'KONGHUCU': 'KONGHUCU',
            'KONGHUCU': 'KONGHUCU',
            'KONGHUCU': 'KONGHUCU'
        }
        
        # Patterns to identify the agama label
        self.label_patterns: List[Tuple[Pattern, int]] = [
            # Format: (pattern, group containing the value)
            (re.compile(r'AGAMA[\s:]*([A-Za-z]+)'), 1),
            (re.compile(r'AGAMA[\s:]'), 0),
            (re.compile(r'AGM[\s:]*([A-Za-z]+)'), 1),
            (re.compile(r'AGM[\s:]'), 0),
            (re.compile(r'AG[\s:]*([A-Za-z]+)'), 1),
            (re.compile(r'AG[\s:]'), 0),
            (re.compile(r'AGAMA'), 0),
        ]
        
        # Common false positives to skip
        self.skip_terms: List[str] = [
            'nik', 'nama', 'tempat', 'lahir', 'jenis', 'kelamin', 'gol', 'darah',
            'rt/rw', 'rt rw', 'kel/desa', 'kecamatan', 'pekerjaan',
            'status', 'perkawinan', 'kewarganegaraan', 'berlaku', 'hingga'
        ]
        
        # Maximum lines to check after finding a label
        self.max_lines_to_check: int = 2
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract religion from the document.
        
        Args:
            context: ParserContext containing the document lines
            
        Returns:
            Extracted religion or None if not found
        """
        # Try to extract by label patterns first (more reliable).
        # Uppercase before matching: label patterns are uppercase and OCR
        # may return mixed case ("Agama : ...").
        for i, line in enumerate(context.raw_lines):
            line = line.strip().upper()
            if not line or self._is_likely_false_positive(line):
                continue

            # Check for label patterns
            for pattern, group_idx in self.label_patterns:
                match = pattern.search(line)
                if match:
                    self._log_debug(context, "Found agama label",
                                  pattern=pattern.pattern, line_number=i)
                    
                    # Try to extract religion from the same line after the label
                    religion = self._extract_after_label(line, pattern, group_idx, context)
                    if religion:
                        return religion
                    
                    # If not found in the same line, check the next few lines
                    religion = self._extract_in_following_lines(context, i)
                    if religion:
                        return religion
        
        # If not found by label, try to find a standalone religion
        return self._find_standalone_religion(context)
    
    def _extract_after_label(self, line: str, pattern: Pattern, group_idx: int,
                           context: ParserContext) -> Optional[str]:
        """Extract religion from the same line as the label."""
        match = pattern.search(line)
        if not match:
            return None
            
        # If group_idx is 0, the pattern didn't capture the value
        if group_idx == 0:
            # Get the text after the match
            text_after = line[match.end():].strip()
            if not text_after:
                return None
                
            # Try to extract religion from the text after the label
            return self._normalize_religion(text_after, context)
        
        # If group_idx > 0, use the captured group
        if match.group(group_idx):
            return self._normalize_religion(match.group(group_idx), context)
            
        return None
    
    def _extract_in_following_lines(self, context: ParserContext, 
                                  start_line: int) -> Optional[str]:
        """Extract religion from lines following a label."""
        end_line = min(start_line + self.max_lines_to_check + 1, len(context.raw_lines))
        
        for i in range(start_line + 1, end_line):
            line = context.raw_lines[i].strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Try to extract religion from the line
            religion = self._normalize_religion(line, context)
            if religion:
                return religion
                
        return None
    
    def _find_standalone_religion(self, context: ParserContext) -> Optional[str]:
        """Try to find a standalone religion in the document."""
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Skip lines that are too long (unlikely to be just a religion)
            if len(line) > 20:
                continue
                
            # Try to extract religion from the line
            religion = self._normalize_religion(line, context)
            if religion:
                self._log_info(context, "Found standalone religion",
                             line_number=i, religion=religion)
                return religion
                
        return None
    
    def _normalize_religion(self, text: str, 
                         context: Optional[ParserContext] = None) -> Optional[str]:
        """Normalize religion text to standard format.
        
        Args:
            text: The text to normalize
            context: Optional ParserContext for logging
            
        Returns:
            Normalized religion or None if invalid
        """
        if not text or not text.strip():
            return None
            
        # Clean and standardize the input
        text = text.upper().strip()
        
        # Remove common prefixes/suffixes
        text = re.sub(r'^[^A-Z0-9]+', '', text)  # Remove non-alphanumeric from start
        text = re.sub(r'[^A-Z0-9]+$', '', text)  # Remove non-alphanumeric from end
        
        # Check if it's a valid religion
        if text in self.valid_religions:
            return self.religion_mapping.get(text, text)
            
        # Check if it's in the mapping
        if text in self.religion_mapping:
            return self.religion_mapping[text]
            
        # Try to match the beginning of the text
        for religion in self.valid_religions:
            if text.startswith(religion) or religion.startswith(text):
                return self.religion_mapping.get(religion, religion)
                
        # Try to match any part of the text
        for religion in self.valid_religions:
            if religion in text:
                return self.religion_mapping.get(religion, religion)

        # Last resort: fuzzy match against the canonical lexicon, so OCR
        # noise not in the hardcoded tables (e.g. ISLAN) still extracts
        return fuzzy_correct(text, AGAMA)
    
    def _is_likely_false_positive(self, text: str) -> bool:
        """Check if the text is likely a false positive for a religion."""
        if not text:
            return True
            
        text_lower = text.lower()
        
        # Skip lines that contain other field labels
        if any(term in text_lower for term in self.skip_terms):
            return True
            
        # Skip lines that are too long (unlikely to be just a religion)
        if len(text) > 30:
            return True
            
        # Skip lines that look like NIK or other numeric IDs
        if re.match(r'^\d+$', text.replace(' ', '')):
            return True
            
        return False
