"""
Berlaku Hingga Extractor for Indonesian ID Card (KTP) OCR processing.

This module provides the BerlakuHinggaExtractor class which is responsible for extracting
the validity period (berlaku hingga) information from Indonesian ID cards.
"""

import re
import logging
from typing import Dict, List, Optional, Pattern, Tuple
from datetime import datetime

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class BerlakuHinggaExtractor(FieldExtractor):
    """Extracts validity period (berlaku hingga) from KTP text."""
    
    def __init__(self):
        super().__init__('berlaku_hingga')
        
        # Common date formats in KTP
        self.date_formats = [
            '%d-%m-%Y',  # 31-12-2099
            '%d/%m/%Y',  # 31/12/2099
            '%d %B %Y',  # 31 Desember 2099
            '%d %b %Y',  # 31 Des 2099
            '%d-%m-%y',  # 31-12-99
            '%d/%m/%y',  # 31/12/99
        ]
        
        # Patterns to identify the berlaku hingga label
        self.label_patterns: List[Tuple[Pattern, int]] = [
            # Format: (pattern, group containing the value)
            (re.compile(r'BERLAKU\s+HINGGA[\s:]*([^\n]+)'), 1),
            (re.compile(r'BERLAKU\s+SEUMUR\s+HIDUP', re.IGNORECASE), 0),
            (re.compile(r'BERLAKU\s+HINGGA[\s:]', re.IGNORECASE), 0),
            (re.compile(r'BERLAKU\s+HINGGA', re.IGNORECASE), 0),
            (re.compile(r'BERLAKU', re.IGNORECASE), 0),
        ]
        
        # Common false positives to skip
        self.skip_terms: List[str] = [
            'nik', 'nama', 'tempat', 'lahir', 'jenis', 'kelamin', 'gol', 'darah',
            'rt/rw', 'rt rw', 'kel/desa', 'kecamatan', 'agama', 'pekerjaan',
            'status', 'perkawinan', 'alamat', 'nama', 'kota', 'kabupaten',
            'kecamatan', 'kelurahan', 'desa', 'kode pos', 'provinsi', 'kab',
            'kec', 'kel', 'kode', 'pos', 'rt', 'rw', 'kewarganegaraan'
        ]
        
        # Maximum lines to check after finding a label
        self.max_lines_to_check: int = 2
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract validity period from the document.
        
        Args:
            context: ParserContext containing the document lines
            
        Returns:
            Extracted validity period or None if not found
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
                    self._log_debug(context, "Found berlaku hingga label", 
                                  pattern=pattern.pattern, line_number=i)
                    
                    # Check for "SEUMUR HIDUP" (lifetime) case
                    if 'SEUMUR HIDUP' in line.upper():
                        return 'SEUMUR HIDUP'
                    
                    # Try to extract date from the same line after the label
                    date_str = self._extract_after_label(line, pattern, group_idx, context)
                    if date_str:
                        return date_str
                    
                    # If not found in the same line, check the next few lines
                    date_str = self._extract_in_following_lines(context, i)
                    if date_str:
                        return date_str
        
        # If not found by label, try to find a standalone date
        return self._find_standalone_date(context)
    
    def _extract_after_label(self, line: str, pattern: Pattern, group_idx: int,
                           context: ParserContext) -> Optional[str]:
        """Extract date from the same line as the label."""
        match = pattern.search(line)
        if not match:
            return None
            
        # If group_idx is 0, the pattern didn't capture the value
        if group_idx == 0:
            # Get the text after the match
            text_after = line[match.end():].strip()
            if not text_after:
                return None
                
            # Try to extract date from the text after the label
            return self._normalize_date(text_after, context)
        
        # If group_idx > 0, use the captured group
        if match.group(group_idx):
            return self._normalize_date(match.group(group_idx), context)
            
        return None
    
    def _extract_in_following_lines(self, context: ParserContext, 
                                  start_line: int) -> Optional[str]:
        """Extract date from lines following a label."""
        end_line = min(start_line + self.max_lines_to_check + 1, len(context.raw_lines))
        
        for i in range(start_line + 1, end_line):
            line = context.raw_lines[i].strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Try to extract date from the line
            date_str = self._normalize_date(line, context)
            if date_str:
                return date_str
                
        return None
    
    def _find_standalone_date(self, context: ParserContext) -> Optional[str]:
        """Try to find a standalone date in the document."""
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Skip lines that are too long (unlikely to be just a date)
            if len(line) > 30:
                continue
                
            # Try to extract date from the line
            date_str = self._normalize_date(line, context)
            if date_str:
                self._log_info(context, "Found standalone date",
                             line_number=i, date=date_str)
                return date_str
                
        return None
    
    def _normalize_date(self, text: str, 
                       context: Optional[ParserContext] = None) -> Optional[str]:
        """Normalize date text to standard format (DD-MM-YYYY).
        
        Args:
            text: The text to normalize
            context: Optional ParserContext for logging
            
        Returns:
            Normalized date string (DD-MM-YYYY) or None if invalid
        """
        if not text or not text.strip():
            return None
            
        # Clean and standardize the input
        text = text.upper().strip()
        
        # Check for "SEUMUR HIDUP" (lifetime) case
        if 'SEUMUR HIDUP' in text:
            return 'SEUMUR HIDUP'
        
        # Remove common prefixes/suffixes
        text = re.sub(r'^[^A-Z0-9]+', '', text)  # Remove non-alphanumeric from start
        text = re.sub(r'[^A-Z0-9]+$', '', text)  # Remove non-alphanumeric from end
        
        # Try to parse the date using different formats
        for date_format in self.date_formats:
            try:
                # Parse the date
                date_obj = datetime.strptime(text, date_format)
                
                # Format as DD-MM-YYYY
                return date_obj.strftime('%d-%m-%Y')
            except ValueError:
                continue
                
        # If we get here, we couldn't parse the date
        return None
    
    def _is_likely_false_positive(self, text: str) -> bool:
        """Check if the text is likely a false positive for a date."""
        if not text:
            return True
            
        text_lower = text.lower()
        
        # Skip lines that contain other field labels
        if any(term in text_lower for term in self.skip_terms):
            return True
            
        # Skip lines that are too long (unlikely to be just a date)
        if len(text) > 30:
            return True
            
        # Skip lines that look like NIK or other numeric IDs
        if re.match(r'^\d+$', text.replace(' ', '')):
            return True
            
        # Skip lines that don't contain any numbers or date-like patterns
        if not re.search(r'\d', text):
            return True
            
        return False
