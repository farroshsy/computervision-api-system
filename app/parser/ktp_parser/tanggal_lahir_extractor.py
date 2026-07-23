"""
Tanggal Lahir Extractor for Indonesian ID Card (KTP) OCR processing.

This module provides the TanggalLahirExtractor class which is responsible for extracting
the date of birth (tanggal lahir) from Indonesian ID cards.
"""

import re
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any, Pattern, Match

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class TanggalLahirExtractor(FieldExtractor):
    """Extracts date of birth (tanggal lahir) from KTP text."""
    
    def __init__(self):
        super().__init__('tanggal_lahir')
        
        # Common date patterns in various formats
        self.date_patterns: List[Tuple[Pattern, str]] = [
            # DD-MM-YYYY or DD/MM/YYYY or DD.MM.YYYY
            (re.compile(r'(\d{2})[-/ .](\d{2})[-/ .](\d{4})'), '%d-%m-%Y'),
            # YYYY-MM-DD or YYYY/MM/DD or YYYY.MM.DD
            (re.compile(r'(\d{4})[-/ .](\d{2})[-/ .](\d{2})'), '%Y-%m-%d'),
            # DD Month YYYY (Indonesian month names)
            (re.compile(r'(\d{1,2})\s+(Januari|Februari|Maret|April|Mei|Juni|Juli|Agustus|September|Oktober|November|Desember)\s+(\d{4})', re.IGNORECASE), 
             '%d %B %Y'),
            # DD-MMM-YY (short month names)
            (re.compile(r'(\d{1,2})[- ](Jan|Feb|Mar|Apr|Mei|Jun|Jul|Ags|Sep|Okt|Nov|Des)[a-z]*[- ](\d{2,4})', re.IGNORECASE),
             '%d-%b-%Y')
        ]
        
        # Patterns to identify the tanggal lahir label.
        # Real KTP prints "Tempat/Tgl Lahir" — TGL then SPACE then LAHIR —
        # so patterns must accept whitespace as the separator, not just /:
        self.label_patterns: List[Pattern] = [
            re.compile(r'TEMPAT\s*/\s*TGL\.?\s+LAHIR', re.IGNORECASE),
            re.compile(r'TGL\.?[\s/:]+LAHIR', re.IGNORECASE),
            re.compile(r'TANGGAL[\s/:]+LAHIR', re.IGNORECASE),
            re.compile(r'TEMPAT[/:]\s*[A-Za-z]+\s*[/:]\s*TGL\.?\s*[/:]', re.IGNORECASE),
            re.compile(r'TEMPAT[/:]\s*[A-Za-z]+\s*[/:]\s*TANGGAL\s*[/:]', re.IGNORECASE),
            re.compile(r'TGL\.?\s*[/:]', re.IGNORECASE),
            re.compile(r'TANGGAL\s*[/:]', re.IGNORECASE),
            re.compile(r'TL[/:]', re.IGNORECASE)
        ]
        
        # Common false positives to skip
        self.skip_terms: List[str] = [
            'nik', 'nama', 'alamat', 'jenis', 'kelamin', 'gol', 'darah',
            'rt/rw', 'rt rw', 'kel/desa', 'kecamatan', 'agama', 'pekerjaan',
            'status', 'perkawinan', 'kewarganegaraan', 'berlaku', 'hingga'
        ]
        
        # Minimum and maximum valid years (adjust based on your needs)
        self.min_year: int = 1900
        self.max_year: int = datetime.now().year
        
        # Maximum lines to check after finding a label
        self.max_lines_to_check: int = 3
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract date of birth from the document.
        
        Args:
            context: ParserContext containing the document lines
            
        Returns:
            Extracted date in YYYY-MM-DD format or None if not found
        """
        # Try to extract by label patterns first (more reliable).
        # NOTE: the standalone false-positive check (length veto <=30 chars)
        # must NOT run here — the real KTP line "Tempat/Tgl Lahir : <place>,
        # <date>" is longer than 30 chars and would veto itself. Only the
        # other-field skip_terms apply for the label search.
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or any(term in line.lower() for term in self.skip_terms):
                continue

            # Check for label patterns
            for pattern in self.label_patterns:
                if pattern.search(line):
                    self._log_debug(context, "Found tanggal lahir label", 
                                  pattern=pattern.pattern, line_number=i)
                    
                    # Try to extract date from the same line after the label
                    date_str = self._extract_after_label(line, pattern, context)
                    if date_str:
                        return date_str
                    
                    # If not found in the same line, check the next few lines
                    date_str = self._extract_in_following_lines(context, i)
                    if date_str:
                        return date_str
        
        # If not found by label, try to find a standalone date
        return self._find_standalone_date(context)
    
    def _extract_after_label(self, line: str, pattern: Pattern, 
                           context: ParserContext) -> Optional[str]:
        """Extract date from the same line as the label."""
        # Extract the part after the label
        match = pattern.search(line)
        if not match:
            return None
            
        # Get the text after the label
        text_after_label = line[match.end():].strip()
        if not text_after_label:
            return None
            
        # Try to parse the date
        return self._parse_date(text_after_label, context)
    
    def _extract_in_following_lines(self, context: ParserContext, 
                                  start_line: int) -> Optional[str]:
        """Extract date from lines following a label."""
        end_line = min(start_line + self.max_lines_to_check + 1, len(context.raw_lines))
        
        for i in range(start_line + 1, end_line):
            line = context.raw_lines[i].strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Try to parse the date
            date_str = self._parse_date(line, context)
            if date_str:
                return date_str
                
        return None
    
    def _find_standalone_date(self, context: ParserContext) -> Optional[str]:
        """Try to find a standalone date in the document."""
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Try to parse the date
            date_str = self._parse_date(line, context)
            if date_str:
                self._log_info(context, "Found standalone date",
                             line_number=i, date=date_str)
                return date_str
                
        return None
    
    def _parse_date(self, text: str, context: Optional[ParserContext] = None) -> Optional[str]:
        """Parse a date string into YYYY-MM-DD format.
        
        Args:
            text: The text to parse
            context: Optional ParserContext for logging
            
        Returns:
            Date in YYYY-MM-DD format or None if invalid
        """
        if not text or not text.strip():
            return None
            
        original_text = text.strip()
        
        # Try each date pattern
        for pattern, date_format in self.date_patterns:
            match = pattern.search(original_text)
            if match:
                try:
                    # Extract date parts from the match
                    if date_format == '%d %B %Y':
                        # Handle month names
                        day = match.group(1)
                        month_name = match.group(2).capitalize()
                        year = match.group(3)
                        date_str = f"{day} {month_name} {year}"
                        date_obj = datetime.strptime(date_str, date_format)
                    elif date_format == '%d-%b-%Y':
                        # Handle short month names
                        day = match.group(1)
                        month_abbr = match.group(2).capitalize()
                        year = match.group(3)
                        # Handle 2-digit years
                        if len(year) == 2:
                            current_year = datetime.now().year
                            century = current_year // 100
                            year = f"{century}{year}"
                        date_str = f"{day}-{month_abbr}-{year}"
                        date_obj = datetime.strptime(date_str, date_format)
                    else:
                        # Handle numeric dates
                        date_str = '-'.join(g for g in match.groups())
                        date_obj = datetime.strptime(date_str, date_format)
                    
                    # Validate year range
                    if not (self.min_year <= date_obj.year <= self.max_year):
                        self._log_debug(context, "Date year out of range",
                                      date=date_obj.strftime('%Y-%m-%d'),
                                      min_year=self.min_year,
                                      max_year=self.max_year)
                        continue
                        
                    # Return in YYYY-MM-DD format
                    return date_obj.strftime('%Y-%m-%d')
                    
                except (ValueError, IndexError) as e:
                    self._log_debug(context, "Failed to parse date",
                                  text=original_text,
                                  pattern=pattern.pattern,
                                  error=str(e))
                    continue
        
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
        if re.match(r'^\d{10,}$', text.replace(' ', '')):
            return True
            
        return False

