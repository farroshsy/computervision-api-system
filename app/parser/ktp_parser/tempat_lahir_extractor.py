"""Tempat Lahir Extractor for Indonesian ID Card (KTP) OCR processing."""

import re
import logging
from typing import Dict, List, Optional, Set, Any

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class TempatLahirExtractor(FieldExtractor):
    """Extracts place of birth (tempat lahir) from KTP text."""
    
    def __init__(self):
        super().__init__('tempat_lahir')
        self.common_places = {
            'JAKARTA', 'BANDUNG', 'SURABAYA', 'MEDAN', 'SEMARANG', 'MAKASSAR',
            'DEPOK', 'TANGERANG', 'BEKASI', 'BOGOR', 'YOGYAKARTA', 'SURAKARTA'
        }
        
        self.ocr_corrections = {
            'J4K4RT4': 'JAKARTA', 'S3L4T4N': 'SELATAN', 'UT4R4': 'UTARA',
            '0': 'O', '1': 'I', '2': 'Z', '3': 'E', '4': 'A', '5': 'S'
        }
        
        self.label_patterns = [
            r'TEMPAT\s*[/:]?\s*T?G?L?\s*[/:]?\s*LAHIR[\s:]*',
            r'T\.?\s*[/:]?\s*L(?:A|AH|AHA|AHIR|AHR|AHRIR|AHRR)[\s:]*',
            r'TP\.?[\s:]*L(?:A|AH|AHA|AHIR|AHR|AHRIR|AHRR)[\s:]*',
            r'TEMPAT[\s:]*',
            r'TL[\s:]*'
        ]
        
        self.skip_terms = [
            'nik', 'nama', 'alamat', 'jenis', 'kelamin', 'gol', 'darah',
            'rt/rw', 'kel/desa', 'kecamatan', 'agama', 'pekerjaan'
        ]
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract place of birth from document lines."""
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Check if this line contains a label pattern
            label_found = False
            for pattern in self.label_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    label_found = True
                    # First try to extract from the current line
                    place = self._extract_after_label(line, pattern, context)
                    if place and place not in ['LAHIR']:  # Skip common false positives
                        return place
                    
                    # Check the next few lines for potential place names
                    lookahead_lines = 3
                    for j in range(1, min(lookahead_lines + 1, len(context.raw_lines) - i)):
                        next_line = context.raw_lines[i + j].strip()
                        if not next_line or self._is_likely_false_positive(next_line):
                            continue
                            
                        # Clean the next line and check if it's a valid place
                        place = self._clean_place(next_line, context, is_partial=True)
                        if place and place not in ['LAHIR']:  # Skip common false positives
                            # If this is a direction, check if the previous line was a place
                            if place in ['UTARA', 'SELATAN', 'TIMUR', 'BARAT', 'PUSAT'] and j > 1:
                                prev_line = context.raw_lines[i + j - 1].strip()
                                if prev_line and not self._is_likely_false_positive(prev_line):
                                    prev_place = self._clean_place(prev_line, context, is_partial=True)
                                    if prev_place and prev_place in self.common_places:
                                        return f"{prev_place} {place}"
                            else:
                                # If we found a place, check if the next line is a direction
                                if j < lookahead_lines and i + j + 1 < len(context.raw_lines):
                                    next_next_line = context.raw_lines[i + j + 1].strip()
                                    if next_next_line and not self._is_likely_false_positive(next_next_line):
                                        next_place = self._clean_place(next_next_line, context, is_partial=True)
                                        if next_place in ['UTARA', 'SELATAN', 'TIMUR', 'BARAT', 'PUSAT']:
                                            return f"{place} {next_place}"
                                return place
                    
                    # If we get here, try combining the next few lines
                    combined = []
                    for j in range(1, min(4, len(context.raw_lines) - i)):
                        next_line = context.raw_lines[i + j].strip()
                        if not next_line or self._is_likely_false_positive(next_line):
                            continue
                        combined.append(next_line)
                        
                        # Try to clean the combined lines
                        combined_text = ' '.join(combined)
                        place = self._clean_place(combined_text, context, is_partial=True)
                        if place and place not in ['LAHIR']:  # Skip common false positives
                            return place
                    
                    # If we still don't have a place, try the extract_in_following_lines method
                    place = self._extract_in_following_lines(context, i)
                    if place and place not in ['LAHIR']:  # Skip common false positives
                        return place
            
            # Do not fallback to standalone to avoid false positives from headers
            if label_found:
                continue
        
        # Conservative standalone fallback for tests: scan lines and accept only valid places
        return self._find_standalone_place(context)
    
    def _extract_after_label(self, line: str, pattern: str, 
                           context: ParserContext) -> Optional[str]:
        cleaned = re.sub(pattern, '', line, flags=re.IGNORECASE).strip()
        return self._clean_place(cleaned, context, is_partial=False) if cleaned else None
    
    def _extract_in_following_lines(self, context: ParserContext, 
                                  start_line: int) -> Optional[str]:
        """Extract place of birth from the next few lines, handling multi-line place names."""
        max_lookahead = 3  # Maximum number of lines to look ahead
        lines_to_check = context.raw_lines[start_line + 1:start_line + 1 + max_lookahead]
        
        # First, try to find a valid place name in the next few lines
        for i, line in enumerate(lines_to_check, 1):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
            # Boundary: stop if admin/other field tokens appear
            if re.search(r"\b(?:PROV(?:\.|INSI)?|KAB(?:\.|UPATEN)?|KOTA|KEC(?:\.|AMATAN)?|KEL(?:\.|URAHAN)?|DESA|ALAMAT|AGAMA|STATUS|PEKERJAAN|BERLAKU|HINGGA|NIK|NAMA|GOL|DARAH|RT|RW)\b", line, re.IGNORECASE):
                break
                
            # Try to clean and extract from the current line
            cleaned_place = self._clean_place(line, context, is_partial=False)
            
            # If we found a place, check if we should combine with next lines for multi-word place names
            if cleaned_place:
                # If this is a known place, check if the next line is a direction
                if i < len(lines_to_check):
                    next_line = lines_to_check[i].strip()
                    if next_line and not self._is_likely_false_positive(next_line):
                        next_place = self._clean_place(next_line, context, is_partial=True)
                        if next_place in ['UTARA', 'SELATAN', 'TIMUR', 'BARAT', 'PUSAT']:
                            return f"{cleaned_place} {next_place}"
                
                # If we found a direction, check if the previous line was a place
                if cleaned_place in ['UTARA', 'SELATAN', 'TIMUR', 'BARAT', 'PUSAT'] and i > 1:
                    prev_line = lines_to_check[i-2].strip()  # i is 1-based, so i-2 is the previous line
                    if prev_line and not self._is_likely_false_positive(prev_line):
                        prev_place = self._clean_place(prev_line, context, is_partial=True)
                        if prev_place and prev_place in self.common_places:
                            return f"{prev_place} {cleaned_place}"
                
                return cleaned_place
        
        # If no place found, try to combine multiple lines that might form a place name
        combined_lines = []
        for line in lines_to_check:
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
            if re.search(r"\b(?:PROV(?:\.|INSI)?|KAB(?:\.|UPATEN)?|KOTA|KEC(?:\.|AMATAN)?|KEL(?:\.|URAHAN)?|DESA|ALAMAT|AGAMA|STATUS|PEKERJAAN|BERLAKU|HINGGA|NIK|NAMA|GOL|DARAH|RT|RW)\b", line, re.IGNORECASE):
                break
            combined_lines.append(line)
        
        if combined_lines:
            combined_text = ' '.join(combined_lines)
            return self._clean_place(combined_text, context, is_partial=True)
        
        return None
    
    def _try_combine_with_previous(self, context: ParserContext, start_line: int, 
                                 current_offset: int, current_place: str) -> Optional[str]:
        """Try to combine the current place with previous lines if they form a valid place name."""
        # If the current place is a direction, try to combine with the previous line
        direction_terms = ['UTARA', 'SELATAN', 'TIMUR', 'BARAT', 'PUSAT']
        if current_place in direction_terms and current_offset > 1:
            prev_line = context.raw_lines[start_line + current_offset - 1].strip()
            prev_place = self._clean_place(prev_line, context)
            if prev_place and prev_place in self.common_places:
                return f"{prev_place} {current_place}"
        
        # If the current place is a common place, check if the next line is a direction
        if current_place in self.common_places and current_offset < len(context.raw_lines) - 1:
            next_line = context.raw_lines[start_line + current_offset + 1].strip()
            next_place = self._clean_place(next_line, context)
            if next_place in direction_terms:
                return f"{current_place} {next_place}"
        
        return None
    
    def _find_standalone_place(self, context: ParserContext) -> Optional[str]:
        """Conservative standalone search using cleaning and admin filtering."""
        if not context or not context.raw_lines:
            return None
        for line in context.raw_lines:
            text = line.strip()
            if not text or self._is_likely_false_positive(text):
                continue
            # Avoid admin/header tokens
            if re.search(r"\b(?:PROV(?:\.|INSI)?|KAB(?:\.|UPATEN)?|KOTA|KEC(?:\.|AMATAN)?|KEL(?:\.|URAHAN)?|DESA|ALAMAT|AGAMA|STATUS|PEKERJAAN|BERLAKU|HINGGA|NIK|NAMA)\b", text, re.IGNORECASE):
                continue
            place = self._clean_place(text, context, is_partial=False)
            if place:
                return place
        return None
    
    def _clean_place(self, text: str, context: Optional[ParserContext] = None, is_partial: bool = False) -> Optional[str]:
        if not text or not text.strip():
            return None
            
        # Convert to uppercase and clean up whitespace
        cleaned = ' '.join(text.upper().split())
        
        # Skip common non-place words that might appear in headers
        if not is_partial and any(word in cleaned for word in ['TEMPAT', 'LAHIR', 'TGL', 'TANGGAL', 'TTL']):
            return None
        
        # Strip a trailing date BEFORE digit->letter OCR corrections; folding
        # first turns "LEBAK, 10-01-1990" into "LEBAK, IO-OI-I99O" and the
        # date can no longer be recognized and removed.
        date_pattern = r'^([A-Z][A-Z\s-]+?)\s*[,;.]?\s*\d{1,2}[-/]\d{1,2}[-/]\d{2,4}.*$'
        date_match = re.match(date_pattern, cleaned)
        if date_match:
            cleaned = date_match.group(1).strip()

        # Apply OCR corrections to the remaining place-only text
        for error, correction in self.ocr_corrections.items():
            cleaned = cleaned.replace(error, correction)

        # Check for common false positives
        if self._is_false_positive(cleaned):
            return None

        # Normalize hyphens (convert " - " to "-")
        cleaned = re.sub(r'\s*-\s*', '-', cleaned)
        
        # Define direction terms and their combinations
        direction_terms = ['UTARA', 'SELATAN', 'TIMUR', 'BARAT', 'PUSAT']
        
        # Check for place + direction patterns (e.g., JAKARTA SELATAN, JAKARTA-SELATAN)
        for place in self.common_places:
            for direction in direction_terms:
                # Check space-separated
                if f"{place} {direction}" in cleaned:
                    return f"{place} {direction}"
                # Check hyphen-separated
                if f"{place}-{direction}" in cleaned:
                    return f"{place}-{direction}"
        
        # Handle place names with various separators
        separators = [',', '.', '_', ';', '|', '/', '\\']
        for sep in separators:
            if sep in cleaned:
                parts = [p.strip() for p in cleaned.split(sep) if p.strip()]
                if len(parts) >= 2:
                    # Try to find a valid place in the parts
                    for i, part in enumerate(parts):
                        if any(p in part for p in self.common_places):
                            # Check if next part is a direction
                            if i + 1 < len(parts) and parts[i + 1] in direction_terms:
                                return f"{part} {parts[i + 1]}"
                            return part
        
        # If we have multiple words, check for place + direction
        words = cleaned.split()
        if len(words) > 1:
            for i, word in enumerate(words):
                if word in self.common_places:
                    # If this is a known place and the next word is a direction, combine them
                    if i + 1 < len(words) and words[i + 1] in direction_terms:
                        return f"{word} {words[i + 1]}"
                    return word
                # Also check if this is a direction that might be part of a place name
                elif word in direction_terms and i > 0 and words[i - 1] in self.common_places:
                    return f"{words[i - 1]} {word}"
        
        # If we get here and the text is a common place, return it
        if any(place == cleaned for place in self.common_places):
            return cleaned
        
        # If this is a direction term, it might be part of a multi-line place name
        if is_partial and cleaned in direction_terms:
            return cleaned
            
        # Skip single-word place names that are too short or look like headers
        if not is_partial and len(words) == 1 and (len(cleaned) < 3 or cleaned in ['TEMPAT', 'LAHIR']):
            return None
        
        # Skip if the text looks like a header or field name
        if not is_partial and any(term in cleaned for term in ['TEMPAT', 'LAHIR', 'TGL', 'TANGGAL']):
            return None
        
        # Remove any remaining non-letter characters except spaces and hyphens
        cleaned = re.sub(r'[^A-Z\s-]', ' ', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        
        # Check if the cleaned text looks like a valid place name
        if (len(cleaned) >= 3 and 
            not self._is_false_positive(cleaned) and
            not any(char.isdigit() for char in cleaned) and
            not any(cleaned.startswith(term) for term in ['RT', 'RW', 'KEL', 'DESA', 'KEC', 'KAB', 'KOTA', 'PROV', 'STATUS', 'KEWARGANEGARAAN', 'BERLAKU', 'HINGGA'])):
            # Require at least one vowel for non-partial place names to filter OCR gibberish
            if not is_partial:
                if not any(vowel in cleaned for vowel in ['A','E','I','O','U']):
                    return None
            return cleaned
        
        return None
    
    def _is_false_positive(self, text: str) -> bool:
        """Check if the text is likely a false positive."""
        text_lower = text.lower()
        
        # Check for common false positive patterns
        false_positive_patterns = [
            r'^\s*(?:nik|nama|alamat|jenis|kelamin|gol|darah|rt/rw|kel/desa|kecamatan|agama|pekerjaan|status|kewarganegaraan|berlaku|hingga)[\s:].*$',
            r'^\s*\d+\s*$',  # Just numbers
            r'^\s*[A-Z]\s*$',  # Single letter
            r'^\s*$'  # Empty or whitespace only
        ]
        
        if any(re.match(pattern, text_lower) for pattern in false_positive_patterns):
            return True
            
        # Check for common false positive terms
        false_positive_terms = [
            'nik', 'nama', 'alamat', 'jenis', 'kelamin', 'gol', 'darah',
            'rt/rw', 'kel/desa', 'kecamatan', 'agama', 'pekerjaan', 'status',
            'kewarganegaraan', 'berlaku', 'hingga', 'kawin', 'wni', 'seumur', 'hidup'
        ]
        
        return any(term in text_lower for term in false_positive_terms)
    
    def _is_likely_false_positive(self, text: str) -> bool:
        text_lower = text.lower()
        return any(term in text_lower for term in self.skip_terms)
