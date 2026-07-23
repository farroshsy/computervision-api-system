"""
Name Extractor Module

This module contains the NameExtractor class for extracting the name field from KTP documents.
"""

import re
from typing import Optional, List, Set, Dict, Any, Tuple

from .base_extractor import FieldExtractor
from app.models.schemas import ParserContext

class NameExtractor(FieldExtractor):
    """Extractor for the name field in KTP documents"""
    
    def __init__(self):
        """Initialize the name extractor with patterns and configurations."""
        super().__init__('nama')
        self.name_labels = ["nama", "name", "kama", "namat"]
        # Noisy label regex for NAMA (handles N4MA, NAMA., NAMA -, N A M A)
        self.noisy_label_pattern = re.compile(r'N[\W_\s]*[A4@][\W_\s]*M[\W_\s]*[A4@]\b', re.IGNORECASE)
        # Accept separators after label
        self.label_sep = re.compile(r'\s*[:\-\.]+\s*')
        self.skip_terms = [
            "ktp", "nik", "rt/rw", "rt", "rw", "kel/desa", "kecamatan", "kabupaten",
            "provinsi", "alamat", "gol", "darah", "agama", "status", "perkawinan",
            "pekerjaan", "kewarganegaraan", "berlaku", "hingga", "tempat", "lahir"
        ]
        self.header_terms = [
            "provinsi", "kabupaten", "kota", "kecamatan", "kelurahan", "desa", "kel.", "kec.",
            "pemerintah", "dinas"
        ]
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract name using multiple patterns and strategies"""
        # First pass: Look for name in various formats
        for i, line in enumerate(context.raw_lines):
            line_upper = line.upper().strip()
            line_lower = line.lower().strip()
            line_stripped = line.strip()
            
            # Skip empty or short lines
            if not line_stripped or len(line_stripped) < 3:
                context.log_debug("Skipping short/empty line", line_number=i, line_content=line)
                continue
                
            context.log_debug("Processing line for name extraction", line_number=i, line_content=line)
            
            # Skip lines that are clearly not names
            if self._should_skip_line(i, line_upper, line_lower, context):
                continue
            
            # Check for name patterns
            name = self._extract_name_from_line(i, line, context)
            if name:
                return name
            
            # Check for name on next line after label
            if i + 1 < len(context.raw_lines):
                name = self._extract_name_from_next_line(i, line, context)
                if name:
                    return name
        
        return None
    
    def _should_skip_line(self, line_num: int, line_upper: str, line_lower: str, 
                         context: ParserContext) -> bool:
        """
        Determine if a line should be skipped during name extraction.
        
        Args:
            line_num: Line number (0-based)
            line_upper: The line in uppercase
            line_lower: The line in lowercase
            context: ParserContext for logging
            
        Returns:
            bool: True if the line should be skipped, False otherwise
        """
        # Skip lines that contain skip terms
        if any(term in line_lower for term in self.skip_terms):
            return True

        # Skip lines that look like headers (only if they're at the very top)
        if line_num < 2:  # First two lines are likely headers like "PROVINSI"
            if any(header in line_upper for header in self.header_terms):
                return True

        # Skip lines that look like dates
        if re.search(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', line_upper):
            return True

        # Skip lines that look like NIK
        if re.search(r'\d{16}', line_upper):
            return True

        # Skip lines containing any numbers unless this line is clearly a name label
        # This allows handling OCR errors like 'Nama : J0HN D0E'
        if re.search(r'\d', line_upper) and not any(term in line_lower for term in self.name_labels):
            return True

        return False

    def _is_admin_label(self, text: str) -> bool:
        """Return True if text equals or starts with a typical admin/field label."""
        t = text.strip().upper()
        labels = {
            'NIK', 'ALAMAT', 'RT', 'RW', 'RT/RW', 'KEL', 'KEL.', 'KELURAHAN', 'DESA', 'KEL/DESA',
            'KEC', 'KEC.', 'KECAMATAN', 'KOTA', 'KABUPATEN', 'PROVINSI', 'AGAMA', 'STATUS', 'PERKAWINAN',
            'PEKERJAAN', 'GOL', 'GOL. DARAH', 'GOLONGAN DARAH', 'NAMA', 'TEMPAT', 'LAHIR', 'TANGGAL LAHIR'
        }
        if t in labels:
            return True
        # Also treat single-word admin tokens as labels
        return any(t.startswith(pref) for pref in ['PROV', 'KAB', 'KOTA', 'KEC', 'KEL', 'DESA'])
    
    def _extract_name_from_line(self, line_num: int, line: str, 
                              context: ParserContext) -> Optional[str]:
        """Extract name from a single line"""
        line_lower = line.lower()
        line_upper = line.upper()
        
        # Case 1: Label with common separators (colon/dash/dot), including noisy label
        if self.noisy_label_pattern.search(line) or any(term in line_lower for term in self.name_labels):
            # Split after the label occurrence
            m = self.noisy_label_pattern.search(line)
            split_pos = None
            if m:
                split_pos = m.end()
            else:
                # fallback: find first occurrence of plain label
                for lb in self.name_labels:
                    idx = line_lower.find(lb)
                    if idx != -1:
                        split_pos = idx + len(lb)
                        break
            if split_pos is not None and split_pos < len(line):
                tail = line[split_pos:]
                # Remove separators only at the immediate start after label, preserve internal hyphens
                tail = re.sub(r'^\s*[:\-\.]+\s*', '', tail)
                name_part = tail.strip()
                # Reject if the extracted part is just an admin/field label
                if name_part and self._is_admin_label(name_part):
                    return None
                if name_part and self._is_valid_name(name_part):
                    normalized_name = self._normalize_name(name_part)
                    self._log_extraction(context, normalized_name, line_number=line_num, pattern="label_with_sep")
                    return normalized_name
        
        # Case 2: Standalone name in all caps (only if it's not a header line)
        if (re.match(r'^[A-Z][A-Z\s\-.,]{2,}$', line.strip()) and 
            not any(term in line_upper for term in self.header_terms)):
            
            # Additional check to avoid capturing location names
            if (line_num < 3 and  # First few lines are likely headers
                not any(label in line_upper for label in ['NAMA', 'NAME'])):  # Unless it's clearly a name label
                return None
                
            name_part = line.strip()
            if self._is_valid_name(name_part) and not self._is_admin_label(name_part):
                normalized_name = self._normalize_name(name_part)
                self._log_extraction(context, normalized_name, line_number=line_num, pattern="standalone_uppercase")
                return normalized_name
        
        return None
    
    def _extract_name_from_next_line(self, line_num: int, line: str, context: ParserContext) -> Optional[str]:
        """Extract name from the next line if current line is a label"""
        line_lower = line.lower()
        next_line = context.raw_lines[line_num + 1].strip()
        
        # Case 1: Current line is a (noisy) name label, next line may start with separator
        if (self.noisy_label_pattern.search(line) or any(term in line_lower for term in self.name_labels)):
            # Remove separators only at start of next line
            tmp = re.sub(r'^\s*[:\-\.]+\s*', '', next_line).strip()
            if self._is_valid_name(tmp) and not self._is_admin_label(tmp):
                normalized_name = self._normalize_name(tmp)
                self._log_extraction(context, normalized_name, line_number=line_num+1, pattern="next_line_after_label")
                return normalized_name
        
        # Case 2: Spillover handling: value split across two lines after label
        if (self.noisy_label_pattern.search(line) or any(term in line_lower for term in self.name_labels)) and (line_num + 2) < len(context.raw_lines):
            part1 = re.sub(r'^\s*[:\-\.]+\s*', '', next_line).strip()
            part2 = context.raw_lines[line_num + 2].strip()
            candidate = f"{part1} {part2}".strip()
            if self._is_valid_name(candidate) and not self._is_admin_label(candidate):
                normalized_name = self._normalize_name(candidate)
                self._log_extraction(context, normalized_name, line_number=line_num+2, pattern="spillover_two_lines")
                return normalized_name
        
        return None
    
    def _normalize_name(self, name: str) -> str:
        """
        Normalize the name by converting to uppercase, fixing common OCR errors,
        and normalizing spaces.
        
        Args:
            name: The name to normalize
            
        Returns:
            Normalized name
        """
        # Common OCR error corrections (e.g., '0' -> 'O', '1' -> 'I', etc.)
        ocr_corrections = {
            '0': 'O', '1': 'I', '2': 'Z', '4': 'A', '5': 'S',
            '6': 'G', '8': 'B', '9': 'G',
            # Add more corrections as needed
        }
        
        # Apply OCR corrections
        corrected_name = []
        for char in name.upper():
            corrected_char = ocr_corrections.get(char, char)
            corrected_name.append(corrected_char)
        
        # Join and normalize spaces
        normalized = ' '.join(''.join(corrected_name).split())
        return normalized
    
    def _is_valid_name(self, text: str) -> bool:
        """
        Check if text looks like a valid name.
        More lenient version to handle OCR errors.
        
        Args:
            text: The text to check
            
        Returns:
            bool: True if the text looks like a valid name, False otherwise
        """
        if not text or len(text.strip()) < 2:
            return False
            
        # Remove any non-alphanumeric characters except spaces, hyphens, and periods
        cleaned = re.sub(r'[^A-Za-z0-9\s\-.]', '', text)

        # Apply OCR corrections on a temp copy before digit checks
        ocr_corrections = str.maketrans({
            '0': 'O', '1': 'I', '2': 'Z', '4': 'A', '5': 'S',
            '6': 'G', '8': 'B', '9': 'G'
        })
        cleaned_for_digits = cleaned.upper().translate(ocr_corrections)

        # Reject names containing any digits after OCR corrections
        if re.search(r'\d', cleaned_for_digits):
            return False
        
        # Should have at least one letter
        if not re.search(r'[A-Za-z]', cleaned):
            return False
            
        # Should have at least one space (first and last name)
        # But be more lenient - some names might be single words
        # if ' ' not in cleaned:
        #     return False
            
        # Should start with a letter (case insensitive)
        if not re.match(r'^[A-Za-z]', cleaned):
            return False
            
        # Should be at least 2 characters long after cleaning
        if len(cleaned) < 2:
            return False
        
        # Vowel presence heuristic to avoid labels like 'NIK' or pure consonant admin tokens
        if not re.search(r'[AEIOU]', cleaned.upper()):
            return False
        
        return True
