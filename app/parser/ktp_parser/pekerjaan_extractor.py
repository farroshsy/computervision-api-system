"""
Pekerjaan Extractor for Indonesian ID Card (KTP) OCR processing.

This module provides the PekerjaanExtractor class which is responsible for extracting
the occupation (pekerjaan) information from Indonesian ID cards.
"""

import re
import logging
from typing import Dict, List, Optional, Pattern, Set, Tuple

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class PekerjaanExtractor(FieldExtractor):
    """Extracts occupation (pekerjaan) from KTP text."""
    
    def __init__(self):
        super().__init__('pekerjaan')
        
        # Common occupations in Indonesia with common OCR errors
        self.common_occupations: Set[str] = {
            'PELAJAR', 'MAHASISWA', 'SISWA', 'MURID', 'PELAJAR',
            'PEGAWAI NEGERI SIPIL', 'PNS', 'PEGAWAI NEGERI', 'PEGAWAI PEMERINTAH',
            'KARYAWAN SWASTA', 'KARYAWAN', 'KARYAWAN PERUSAHAAN',
            'WIRASWASTA', 'PENGUSAHA', 'PEDAGANG', 'PEDAGANG KAKI LIMA',
            'BURUH', 'TUKANG', 'TUKANG KAYU', 'TUKANG BANGUNAN',
            'PETANI', 'NELAYAN', 'PETERNAK', 'PETANI NELAYAN',
            'GURU', 'DOSEN', 'PENGAJAR', 'PENDIDIK',
            'DOKTER', 'PERAWAT', 'BIDAN', 'BIDAN DESA',
            'TENTARA NASIONAL INDONESIA', 'TNI', 'POLISI', 'POLRI',
            'PENSIUNAN', 'PENSIUNAN NEGERI', 'PENSIUNAN SWASTA',
            'IBU RUMAH TANGGA', 'RT', 'RUMAH TANGGA', 'MENGURUS RUMAH TANGGA',
            'TIDAK BEKERJA', 'PENGANGGURAN', 'BELUM BEKERJA', 'TIDAK ADA',
            'LAIN-LAIN', 'LAINNYA', 'LAIN', 'LAIN-LAIN', 'LAINNYA',
        }
        
        # Mapping of OCR errors to correct values
        self.occupation_mapping: Dict[str, str] = {
            # Common OCR errors
            'PELAJAR': 'PELAJAR',
            'PELAJAR': 'PELAJAR',
            'PELAJAR': 'PELAJAR',
            'PELAJAR': 'PELAJAR',
            'PELAJAR': 'PELAJAR',
            'MAHASISWA': 'MAHASISWA',
            'MAHASISWA': 'MAHASISWA',
            'MAHASISWA': 'MAHASISWA',
            'MAHASISWA': 'MAHASISWA',
            'MAHASISWA': 'MAHASISWA',
            'PNS': 'PEGAWAI NEGERI SIPIL',
            'PEGAWAI NEGERI SIPIL': 'PEGAWAI NEGERI SIPIL',
            'PEGAWAI NEGERI': 'PEGAWAI NEGERI SIPIL',
            'PEGAWAI PEMERINTAH': 'PEGAWAI NEGERI SIPIL',
            'PEGAWAI NEGERI SIPIL': 'PEGAWAI NEGERI SIPIL',
            'KARYAWAN SWASTA': 'KARYAWAN SWASTA',
            'KARYAWAN': 'KARYAWAN SWASTA',
            'KARYAWAN PERUSAHAAN': 'KARYAWAN SWASTA',
            'WIRASWASTA': 'WIRASWASTA',
            'PENGUSAHA': 'WIRASWASTA',
            'PEDAGANG': 'PEDAGANG',
            'PEDAGANG KAKI LIMA': 'PEDAGANG',
            'BURUH': 'BURUH',
            'TUKANG': 'TUKANG',
            'TUKANG KAYU': 'TUKANG KAYU',
            'TUKANG BANGUNAN': 'TUKANG BANGUNAN',
            'PETANI': 'PETANI',
            'NELAYAN': 'NELAYAN',
            'PETERNAK': 'PETERNAK',
            'PETANI NELAYAN': 'PETANI/NELAYAN',
            'GURU': 'GURU',
            'DOSEN': 'DOSEN',
            'PENGAJAR': 'GURU',
            'PENDIDIK': 'GURU',
            'DOKTER': 'DOKTER',
            'PERAWAT': 'PERAWAT',
            'BIDAN': 'BIDAN',
            'BIDAN DESA': 'BIDAN',
            'TNI': 'TENTARA NASIONAL INDONESIA',
            'TENTARA NASIONAL INDONESIA': 'TENTARA NASIONAL INDONESIA',
            'POLISI': 'POLRI',
            'POLRI': 'POLRI',
            'PENSIUNAN': 'PENSIUNAN',
            'PENSIUNAN NEGERI': 'PENSIUNAN',
            'PENSIUNAN SWASTA': 'PENSIUNAN',
            'IBU RUMAH TANGGA': 'IBU RUMAH TANGGA',
            'RT': 'IBU RUMAH TANGGA',
            'RUMAH TANGGA': 'IBU RUMAH TANGGA',
            'MENGURUS RUMAH TANGGA': 'IBU RUMAH TANGGA',
            'TIDAK BEKERJA': 'TIDAK BEKERJA',
            'PENGANGGURAN': 'TIDAK BEKERJA',
            'BELUM BEKERJA': 'TIDAK BEKERJA',
            'TIDAK ADA': 'TIDAK BEKERJA',
            'LAIN-LAIN': 'LAINNYA',
            'LAINNYA': 'LAINNYA',
            'LAIN': 'LAINNYA',
            'LAIN-LAIN': 'LAINNYA',
            'LAINNYA': 'LAINNYA',
        }
        
        # Patterns to identify the pekerjaan label
        self.label_patterns: List[Tuple[Pattern, int]] = [
            # Format: (pattern, group containing the value)
            (re.compile(r'PEKERJAAN[\s:]*([A-Za-z\s\-\/]+)'), 1),
            (re.compile(r'PEKERJAAN[\s:]'), 0),
            (re.compile(r'PEKERJAAN'), 0),
            (re.compile(r'PEKERJAAN'), 0),
            (re.compile(r'PEKERJAAN'), 0),
            (re.compile(r'PEKERJAAN'), 0),
            (re.compile(r'PEKERJAAN'), 0),
            # OCR-tolerant label (e.g., PEKERJ4AN, PEKERIAAN)
            (re.compile(r'P[E3]K[E3]R[JG]A[ANN4][\s:]*'), 0),
        ]
        
        # Common false positives to skip
        self.skip_terms: List[str] = [
            'nik', 'nama', 'tempat', 'lahir', 'jenis', 'kelamin', 'gol', 'darah',
            'rt/rw', 'rt rw', 'kel/desa', 'kecamatan', 'agama', 'status',
            'perkawinan', 'kewarganegaraan', 'berlaku', 'hingga'
        ]
        
        # Maximum lines to check after finding a label
        self.max_lines_to_check: int = 2
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract occupation from the document.
        
        Args:
            context: ParserContext containing the document lines
            
        Returns:
            Extracted occupation or None if not found
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
                    self._log_debug(context, "Found pekerjaan label", 
                                  pattern=pattern.pattern, line_number=i)
                    
                    # Try to extract occupation from the same line after the label
                    occupation = self._extract_after_label(line, pattern, group_idx, context)
                    if occupation:
                        return occupation
                    
                    # If not found in the same line, check the next few lines
                    occupation = self._extract_in_following_lines(context, i)
                    if occupation:
                        return occupation
        
        # No standalone fallback to avoid capturing headers/admin text
        return None
    
    def _extract_after_label(self, line: str, pattern: Pattern, group_idx: int,
                           context: ParserContext) -> Optional[str]:
        """Extract occupation from the same line as the label."""
        match = pattern.search(line)
        if not match:
            return None
            
        # If group_idx is 0, the pattern didn't capture the value
        if group_idx == 0:
            # Get the text after the match
            text_after = line[match.end():].strip()
            if not text_after:
                return None
            # Guard against admin/header tokens accidentally following the label
            if re.search(r"\b(?:PROV(?:\.|INSI)?|KAB(?:\.|UPATEN)?|KOTA|KEC(?:\.|AMATAN)?|KEL(?:\.|URAHAN)?|DESA|ALAMAT|NIK|NAMA|AGAMA|STATUS|BERLAKU|HINGGA)\b",
                         text_after, re.IGNORECASE):
                return None
                
            # Try to extract occupation from the text after the label
            return self._normalize_occupation(text_after, context)
        
        # If group_idx > 0, use the captured group
        if match.group(group_idx):
            return self._normalize_occupation(match.group(group_idx), context)
            
        return None
    
    def _extract_in_following_lines(self, context: ParserContext, 
                                  start_line: int) -> Optional[str]:
        """Extract occupation from lines following a label."""
        end_line = min(start_line + self.max_lines_to_check + 1, len(context.raw_lines))
        
        for i in range(start_line + 1, end_line):
            line = context.raw_lines[i].strip()
            if not line or self._is_likely_false_positive(line):
                continue
            # Stop on boundaries/admin tokens
            if re.search(r"\b(?:PROV(?:\.|INSI)?|KAB(?:\.|UPATEN)?|KOTA|KEC(?:\.|AMATAN)?|KEL(?:\.|URAHAN)?|DESA|ALAMAT|NIK|NAMA|AGAMA|STATUS|BERLAKU|HINGGA)\b", line, re.IGNORECASE):
                return None
            
            # Try to extract occupation from the line
            occupation = self._normalize_occupation(line, context)
            if occupation:
                return occupation
                
        return None
    
    def _find_standalone_occupation(self, context: ParserContext) -> Optional[str]:
        """Disabled to reduce false positives from headers/admin lines."""
        return None
    
    def _normalize_occupation(self, text: str, 
                            context: Optional[ParserContext] = None) -> Optional[str]:
        """Normalize occupation text to standard format.
        
        Args:
            text: The text to normalize
            context: Optional ParserContext for logging
            
        Returns:
            Normalized occupation or None if invalid
        """
        if not text or not text.strip():
            return None
            
        # Clean and standardize the input
        text = text.upper().strip()
        
        # Remove common prefixes/suffixes
        text = re.sub(r'^[^A-Z0-9]+', '', text)  # Remove non-alphanumeric from start
        text = re.sub(r'[^A-Z0-9]+$', '', text)  # Remove non-alphanumeric from end
        
        # Check if it's a valid occupation
        if text in self.common_occupations:
            return self.occupation_mapping.get(text, text)
            
        # Check if it's in the mapping
        if text in self.occupation_mapping:
            return self.occupation_mapping[text]
            
        # Try to match the beginning of the text
        for occupation in sorted(self.common_occupations, key=len, reverse=True):
            if text.startswith(occupation) or occupation.startswith(text):
                return self.occupation_mapping.get(occupation, occupation)
                
        # Try to match any part of the text
        for occupation in sorted(self.common_occupations, key=len, reverse=True):
            if occupation in text:
                return self.occupation_mapping.get(occupation, occupation)
        
        # Otherwise, do not guess
        return None
    
    def _is_likely_false_positive(self, text: str) -> bool:
        """Check if the text is likely a false positive for an occupation."""
        if not text:
            return True
            
        text_lower = text.lower()
        
        # Skip lines that contain other field labels
        if any(term in text_lower for term in self.skip_terms):
            return True
        # Skip administrative headers
        if re.search(r"\b(?:prov(?:\.|insi)?|provinsi|kab(?:\.|upaten)?|kota|kecamatan|kel(?:\.|urahan)?|desa)\b", text_lower, re.IGNORECASE):
            return True
            
        # Skip lines that are too short (unlikely to be an occupation)
        if len(text) < 2:
            return True
            
        # Skip lines that are too long (unlikely to be just an occupation)
        if len(text) > 100:
            return True
            
        # Skip lines that look like NIK or other numeric IDs
        if re.match(r'^\d+$', text.replace(' ', '')):
            return True
            
        return False
