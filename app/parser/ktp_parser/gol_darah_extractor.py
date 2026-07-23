"""Golongan Darah Extractor for Indonesian ID Card (KTP) OCR processing."""

import re
import logging
from typing import Dict, List, Optional, Pattern, Set

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class GolDarahExtractor(FieldExtractor):
    """Extracts blood type (golongan darah) from KTP text."""
    
    def __init__(self):
        super().__init__('gol_darah')
        self.valid_blood_types = {'A', 'B', 'AB', 'O', '0', '8', 'A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-'}
        self.blood_type_mapping = {
            '0': 'O', '8': 'B', 'A+': 'A', 'A-': 'A', 'B+': 'B', 'B-': 'B',
            'AB+': 'AB', 'AB-': 'AB', 'O+': 'O', 'O-': 'O', 'A8': 'AB', 'A0': 'A',
            'B0': 'B', 'AB0': 'AB', 'AO': 'A', 'BO': 'B', 'A ': 'A', 'B ': 'B', 'O ': 'O', 'AB ': 'AB'
        }
        self.label_patterns = [
            r'GOL\.?\s*DARAH\s*[:.]?\s*([A-Z0-9+-]+)',
            r'GOL\.?\s*DARAH\s*[:.]?',
            r'GOL\.?\s*DARAN\s*[:.]?\s*([A-Z0-9+-]+)',
            r'GOL\.?\s*DARA\s*[:.]?\s*([A-Z0-9+-]+)',
            r'GOL\.?\s*DAR\s*[:.]?\s*([A-Z0-9+-]+)',
            r'GOL\.?\s*DAN\s*[:.]?\s*([A-Z0-9+-]+)'
        ]
        self.skip_terms = [
            'nik', 'nama', 'tempat', 'lahir', 'jenis', 'kelamin',
            'rt/rw', 'kel/desa', 'kecamatan', 'agama', 'pekerjaan'
        ]
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract blood type from the document."""
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            for pattern in self.label_patterns:
                match = re.search(pattern, line, re.IGNORECASE)
                if match:
                    # Try to extract from same line
                    if match.groups():
                        blood_type = self._normalize_blood_type(match.group(1).strip(), context)
                        if blood_type:
                            return blood_type
                    
                    # Check next line if available
                    if i + 1 < len(context.raw_lines):
                        next_line = context.raw_lines[i + 1].strip()
                        if next_line and not self._is_likely_false_positive(next_line):
                            blood_type = self._normalize_blood_type(next_line, context)
                            if blood_type:
                                return blood_type
        
        # Try to find standalone blood type
        return self._find_standalone_blood_type(context)
    
    def _normalize_blood_type(self, text: str, context: Optional[ParserContext] = None) -> Optional[str]:
        """Normalize blood type to standard format."""
        if not text:
            return None
            
        # Clean and standardize the input
        text = text.upper().strip()
        
        # Remove common prefixes/suffixes
        text = re.sub(r'^GOL\.?\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+', '', text)
        
        # Check if it's a valid blood type
        if text in self.valid_blood_types:
            return self.blood_type_mapping.get(text, text)
            
        # Check if it's in the mapping
        if text in self.blood_type_mapping:
            return self.blood_type_mapping[text]
            
        # Try to extract from longer text
        for bt in self.valid_blood_types:
            if bt in text:
                return self.blood_type_mapping.get(bt, bt)
                
        return None
    
    def _find_standalone_blood_type(self, context: ParserContext) -> Optional[str]:
        """Look for standalone blood type in the document."""
        for line in context.raw_lines:
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Check if the line is just a blood type
            blood_type = self._normalize_blood_type(line, context)
            if blood_type:
                return blood_type
                
        return None
    
    def _is_likely_false_positive(self, text: str) -> bool:
        """Check if the text is likely a false positive for a blood type."""
        if not text:
            return True
            
        text_lower = text.lower()
        return any(term in text_lower for term in self.skip_terms)

