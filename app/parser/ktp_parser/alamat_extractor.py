"""
Alamat Extractor for Indonesian ID Card (KTP) OCR processing.

This module provides the AlamatExtractor class which is responsible for extracting
the address (alamat) information from Indonesian ID cards.
"""

import re
import logging
from typing import Any, Dict, List, Optional, Pattern, Set, Tuple

from app.parser.ktp_parser.constants import (
    STREET_CUES,
    ABBREVIATIONS_DEBUG,
    ABBREVIATIONS_NORMAL,
    NAME_TYPO_PATTERNS,
)

from app.models.schemas import ParserContext
from .base_extractor import FieldExtractor

logger = logging.getLogger(__name__)

class AlamatExtractor(FieldExtractor):
    """Extracts address (alamat) from KTP text."""
    
    def __init__(self):
        super().__init__('alamat')
        
        # Common address indicators (from shared constants)
        self.address_indicators: Set[str] = set(STREET_CUES)
        
        # Patterns to identify the alamat label
        self.label_patterns: List[Tuple[Pattern, int]] = [
            # Format: (pattern, group containing the value)
            (re.compile(r'ALAMAT[\s:]+([^\n]+)', re.IGNORECASE), 1),  # 'ALAMAT : JL. CONTOH NO. 123'
            (re.compile(r'ALAMAT[\s:]+', re.IGNORECASE), 0),  # 'ALAMAT : ' (value follows)
            (re.compile(r'ALAMAT', re.IGNORECASE), 0),  # 'ALAMAT' (value follows)
            (re.compile(r'ALMT[\s:]+([^\n]+)', re.IGNORECASE), 1),  # 'ALMT : JL. CONTOH NO. 123'
            # Common OCR typos for 'Alamat'
            (re.compile(r'ALAMAL[\s:]+([^\n]+)', re.IGNORECASE), 1),  # 'ALAMAL : JL. CONTOH NO. 123'
            (re.compile(r'ALAMAN[\s:]+([^\n]+)', re.IGNORECASE), 1),  # 'ALAMAN : JL. CONTOH NO. 123'
            (re.compile(r'ALANAT[\s:]+([^\n]+)', re.IGNORECASE), 1),  # 'ALANAT : JL. CONTOH NO. 123'
            (re.compile(r'ALAMAR[\s:]+([^\n]+)', re.IGNORECASE), 1),  # 'ALAMAR : JL. CONTOH NO. 123'
            (re.compile(r'A\s*LAMAT[\s:]+([^\n]+)', re.IGNORECASE), 1),  # 'A LAMAT : ...'
            (re.compile(r'ALAMA[TI1][\s:]+([^\n]+)', re.IGNORECASE), 1),  # 'ALAMAT/ALAMAI'
            (re.compile(r'AL4MAT[\s:]+([^\n]+)', re.IGNORECASE), 1),  # 'AL4MAT'
            (re.compile(r'ALAMA7[\s:]+([^\n]+)', re.IGNORECASE), 1),  # 'ALAMA7' noisy OCR
        ]
        
        # Common false positives to skip
        self.skip_terms: List[str] = [
            'nik', 'nama', 'tempat', 'lahir', 'jenis', 'kelamin', 'gol', 'darah',
            'agama', 'status', 'perkawinan', 'pekerjaan', 'kewarganegaraan',
            'berlaku', 'hingga', 'masa', 'berlaku', 'sampai', 'dengan', 'tgl',
            'tanggal', 'lahir', 'tgl. lahir', 'tempat/tgl', 'tempat/tgl lahir'
        ]
        
        # Maximum lines to check after finding a label
        self.max_lines_to_check: int = 5
        
        # Minimum and maximum length for a valid address
        self.min_address_length: int = 5
        self.max_address_length: int = 200
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract address from the document.
        
        Args:
            context: ParserContext containing the document lines
            
        Returns:
            Extracted address or None if not found
        """
        self._log_debug("Starting address extraction", context)
        
        # First, try to find and log all potential address lines
        potential_addresses = []
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line:
                continue
                
            # Check if this line looks like it contains an address
            if self._looks_like_address(line, context):
                potential_addresses.append((i, line))
                self._log_debug(f"Potential address at line {i}: '{line}'", context)
        
        # Try to extract by label patterns first (more reliable)
        self._log_debug(f"Trying to extract address using label patterns", context)
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Check for label patterns
            for pattern, group_idx in self.label_patterns:
                match = pattern.search(line)
                if match:
                    self._log_debug(f"Found alamat label pattern '{pattern.pattern}' at line {i}: '{line}'", context)
                    
                    # Try to extract address from the same line after the label
                    self._log_debug(f"Attempting to extract address from line {i} after label", context)
                    address = self._extract_after_label(line, pattern, group_idx, context)
                    if address:
                        self._log_debug(f"Successfully extracted address from line {i}: '{address}'", context)
                        return self._package_result(address, base_conf=0.9, provenance={
                            'method': 'label_same_line',
                            'line_index': i,
                            'pattern': pattern.pattern,
                        }, context=context)
                    
                    # If not found in the same line, check the next few lines
                    self._log_debug(f"Address not found in line {i}, checking following lines", context)
                    address = self._extract_in_following_lines(context, i)
                    if address:
                        self._log_debug(f"Found address in following lines: '{address}'", context)
                        return self._package_result(address, base_conf=0.8, provenance={
                            'method': 'label_following_lines',
                            'start_line_index': i,
                            'pattern': pattern.pattern,
                        }, context=context)
        
        # Strict standalone: look for a street-cue line and accumulate RT/RW and optional Kelurahan
        if context and getattr(context, 'allow_standalone_address', True):
            addr = self._extract_standalone_with_cues(context)
            if addr:
                return self._package_result(addr, base_conf=0.7, provenance={'method': 'standalone_cues'}, context=context)
        return None

    def _package_result(self, value: str, base_conf: float, provenance: Dict[str, Any], context: Optional[ParserContext]) -> Dict[str, Any]:
        """Package extracted value with confidence and provenance.
        Confidence is adjusted by OCR quality proxy.
        """
        try:
            q = float(getattr(context, 'ocr_quality', 0.5)) if context else 0.5
        except Exception:
            q = 0.5
        # Blend base confidence with OCR quality (tempered)
        conf = max(0.0, min(1.0, base_conf * (0.6 + 0.4 * q)))
        prov = dict(provenance or {})
        # Return plain string for backward-compat unless structured_output requested
        if not (context and getattr(context, 'structured_output', False)):
            return value
        return {'value': value, 'confidence': conf, 'provenance': prov}
    def _extract_standalone_with_cues(self, context: ParserContext) -> Optional[str]:
        if not context or not context.raw_lines:
            return None
        for i, line in enumerate(context.raw_lines):
            text = line.strip()
            if not text or self._is_likely_false_positive(text):
                continue
            # Must start with a core street cue (prefer JL/JLN/JALAN/GG/GANG)
            if not any(cue in text.upper() for cue in ['JL', 'JLN', 'JALAN', 'GG', 'GANG']):
                continue
            first = self._clean_address(text, context)
            if not first:
                continue
            parts = [first]
            # Accumulate next up to 3 lines for RT/RW and Kelurahan
            for j in range(i + 1, min(i + 4, len(context.raw_lines))):
                nxt = context.raw_lines[j].strip()
                if not nxt or self._is_likely_false_positive(nxt):
                    continue
                if re.search(r"\b(?:PROV(?:\.|INSI)?|KAB(?:\.|UPATEN)?|KOTA|AGAMA|STATUS|PEKERJAAN|BERLAKU|HINGGA|NIK|NAMA)\b", nxt, re.IGNORECASE):
                    break
                if re.search(r"\bRT\b.*\bRW\b|\bRT\s*\d+\b|\bRW\s*\d+\b", nxt, re.IGNORECASE):
                    parts.append(re.sub(r"\s+", " ", nxt.upper()).strip())
                    continue
                if re.search(r"\bKEL(?:\.|URAHAN)?\b|\bDESA\b|\bKEL\s*/\s*DESA\b", nxt, re.IGNORECASE):
                    parts.append(re.sub(r"\s+", " ", nxt.upper()).strip())
                    continue
                # If neither RT/RW nor kelurahan nor another street line, stop if we've already collected
                if parts:
                    break
            if parts:
                return ' '.join(parts)
        return None

    def _clean_label_line(self, line: str, context: ParserContext) -> Optional[str]:
        """Clean and extract address from a line with a label and colon.
        
        Args:
            line: The line containing the address with a label
            context: ParserContext for logging
            
        Returns:
            The cleaned address if found, None otherwise
        """
        if ':' not in line:
            return None
            
        # Try to match common label patterns with typos
        label_patterns = [
            r'ALAMAT', r'ALMT', r'ALAMAL', r'ALAMAN', 
            r'ALANAT', r'ALAMAR', r'ALAMT', r'ALAMTA'
        ]
        
        # Check if line starts with any of the label patterns (case insensitive)
        for label in label_patterns:
            if re.match(fr'^{label}\s*:', line, re.IGNORECASE):
                parts = line.split(':', 1)
                if len(parts) > 1:
                    address = parts[1].strip()
                    self._log_debug(f"Extracted after label '{label}': '{address}'", context)
                    
                    # Clean and normalize the address
                    cleaned_address = self._clean_address(address, context)
                    if cleaned_address:
                        self._log_debug(f"Returning cleaned address from label: '{cleaned_address}'", context)
                        return cleaned_address
                    
                    # Do not return fallback without validating as address; require street cues via _clean_address
                    return None
        
        return None
    
    def _extract_after_label(self, line: str, pattern: Pattern, group_idx: int,
                           context: ParserContext) -> Optional[str]:
        """Extract address from the same line as the label."""
        self._log_debug(f"Extracting address from line: {line}", context)
        self._log_debug(f"Using pattern: {pattern.pattern}, group_idx: {group_idx}", context)
        
        # First, try to handle label with colon (including typos)
        cleaned = self._clean_label_line(line, context)
        if cleaned:
            return cleaned
        
        # Try to match the pattern
        match = pattern.search(line)
        if match:
            self._log_debug(f"Pattern matched: {match.group(0)}", context)
            
            # If the pattern has a capture group, use that as the address
            if group_idx > 0 and len(match.groups()) >= group_idx:
                address = match.group(group_idx).strip()
                # Hard stop at RT/RW or administrative labels on the same line
                address = re.split(r"\b(?:RT\s*/?\s*RW|RT|RW|KEL(?:\.|/)?|KELURAHAN|DESA|KEC(?:\.|/)?|KECAMATAN|KAB(?:\.|/)?|KABUPATEN|KOTA|PROV(?:\.|INSi)?|PROVINSI)\b", address, maxsplit=1)[0].strip()
                if address:
                    upper_addr = address.upper()
                    has_street_cue = any(cue in upper_addr for cue in STREET_CUES)
                    if not has_street_cue:
                        return None
                    self._log_debug(f"Extracted from capture group {group_idx}: '{address}'", context)
                    
                    # Clean up the address
                    address = re.sub(r'^[^A-Z0-9.]+', '', address)  # Remove leading non-alphanumeric (except periods)
                    address = re.sub(r'[^A-Z0-9\s.,-]+$', '', address)  # Remove trailing non-alphanumeric
                    address = re.sub(r'\s+', ' ', address).strip()  # Normalize whitespace
                    
                    if address and len(address) >= self.min_address_length:
                        self._log_debug(f"Returning cleaned address from capture group: '{address}'", context)
                        return address
            
            # Otherwise, get everything after the match
            text_after = line[match.end():].strip()
            if text_after:
                self._log_debug(f"Text after match: '{text_after}'", context)
                
                # Clean up the address
                # Hard stop at RT/RW or administrative labels on the same line
                text_after = re.split(r"\b(?:RT\s*/?\s*RW|RT|RW|KEL(?:\.|/)?|KELURAHAN|DESA|KEC(?:\.|/)?|KECAMATAN|KAB(?:\.|/)?|KABUPATEN|KOTA|PROV(?:\.|INSi)?|PROVINSI)\b", text_after, maxsplit=1)[0].strip()
                upper_after = text_after.upper()
                has_street_cue = any(cue in upper_after for cue in STREET_CUES)
                if not has_street_cue:
                    return None
                text_after = re.sub(r'^[^A-Z0-9.]+', '', text_after)  # Remove leading non-alphanumeric (except periods)
                text_after = re.sub(r'[^A-Z0-9\s.,-]+$', '', text_after)  # Remove trailing non-alphanumeric
                text_after = re.sub(r'\s+', ' ', text_after).strip()  # Normalize whitespace
                
                if text_after and len(text_after) >= self.min_address_length:
                    self._log_debug(f"Returning cleaned address from text after match: '{text_after}'", context)
                    return text_after
        
        # No valid address found on this line
        self._log_debug("No address found in line (after label)", context)
        return None
        
    
    def _extract_in_following_lines(self, context: ParserContext, 
                                  start_line: int) -> Optional[str]:
        """Extract address from lines following a label."""
        self._log_debug(f"Looking for address in lines after line {start_line}", context)
        
        end_line = min(start_line + self.max_lines_to_check + 1, len(context.raw_lines))
        address_parts = []
        started = False  # become True after we accept the first address content line
        
        for i in range(start_line + 1, end_line):
            line = context.raw_lines[i].strip()
            self._log_debug(f"Checking line {i}: '{line}'", context)
            
            if not line:
                self._log_debug("Skipping empty line", context)
                continue
            
            if self._is_likely_false_positive(line):
                self._log_debug(f"Skipping line (false positive): '{line}'", context)
                continue

            # Stop at boundaries like other field labels or admin headers (but allow RT/RW and Kelurahan lines)
            if re.search(r"\b(?:PROV(?:\.|INSI)?|KAB(?:\.|UPATEN)?|KOTA|AGAMA|STATUS|PEKERJAAN|BERLAKU|HINGGA|NIK|NAMA)\b", line, re.IGNORECASE):
                break
            # Allow RT/RW lines, but skip if the line is just the label without values
            if re.search(r"\bRT\b.*\bRW\b|\bRT\s*\d+\b|\bRW\s*\d+\b", line, re.IGNORECASE):
                candidate = re.sub(r"\s+", " ", line.upper()).strip()
                if re.fullmatch(r"RT\s*/?\s*RW", candidate):
                    # Bare RT/RW label without numbers; skip
                    continue
                address_parts.append(candidate)
                started = True
                continue
            # Allow Kelurahan/Desa line as part of address block
            if re.search(r"\bKEL(?:\.|URAHAN)?\b|\bDESA\b|\bKEL\s*/\s*DESA\b", line, re.IGNORECASE):
                address_parts.append(re.sub(r"\s+", " ", line.upper()).strip())
                started = True
                continue
            # Include normal street or continuation lines
            cleaned_line = self._clean_address(line, context)
            if cleaned_line:
                upper_line = line.upper()
                address_parts.append(cleaned_line)
                started = True
                continue
            # If not a clear address line but we haven't started yet, accept the first non-empty, non-boundary line as the start
            if not started:
                address_parts.append(re.sub(r"\s+", " ", line.upper()).strip())
                started = True
                continue
            # If we've started collecting and hit a non-address/other content line, stop
            if started:
                break
        
        if address_parts:
            address = ' '.join(address_parts).strip()
            # Suppress degenerate result that is only RT/RW
            if re.fullmatch(r"RT\s*/?\s*RW", address.upper()):
                self._log_debug("Composed address is only 'RT/RW'; suppressing", context)
                return None
            self._log_debug(f"Combined address from multiple lines: '{address}'", context)
            return address
            
        self._log_debug("No address found in following lines", context)
        return None
    
    def _find_standalone_address(self, context: ParserContext) -> Optional[str]:
        """Try to find a standalone address in the document.
        
        If an address is found, it will also check the next line for RT/RW information
        and append it to the address if found.
        """
        for i, line in enumerate(context.raw_lines):
            line = line.strip()
            if not line or self._is_likely_false_positive(line):
                continue
                
            # Skip lines that are too short or too long
            if not (self.min_address_length <= len(line) <= self.max_address_length):
                continue
                
            # Check if the line looks like an address and has street cues
            if self._looks_like_address(line, context):
                upper_line = line.upper()
                has_street_cue = any(cue in upper_line for cue in STREET_CUES.union({'RT', 'RW'}))
                if not has_street_cue:
                    continue
                address = line
                self._log_info(context, "Found standalone address",
                             line_number=i, address=address)
                
                # Check the next line for RT/RW information
                if i + 1 < len(context.raw_lines):
                    next_line = context.raw_lines[i + 1].strip()
                    rt_rw_match = re.search(r'RT\s*(\d+)\s*RW\s*(\d+)', next_line, re.IGNORECASE)
                    if rt_rw_match:
                        rt = rt_rw_match.group(1).zfill(3)
                        rw = rt_rw_match.group(2).zfill(3)
                        rt_rw = f"RT {rt} RW {rw}"
                        address = f"{address} {rt_rw}"
                        self._log_debug(f"Added RT/RW from next line: {rt_rw}", context)
                
                return address
                
        return None
    
    def _clean_address(self, text: str, 
                      context: Optional[ParserContext] = None) -> Optional[str]:
        """Clean and normalize the address text.
        
        Args:
            text: The text to clean
            context: Optional ParserContext for logging
            
        Returns:
            Cleaned address or None if invalid
        """
        if not text or not text.strip():
            return None
            
        # Clean and standardize the input
        text = text.strip()
        
        # Convert to uppercase first
        text = text.upper()
        
        # Decide normalization style based on debug flag in context
        debug_mode = bool(context and getattr(context, 'debug', False))

        # Fix common OCR typo where 'JL' is read as 'UL' at the start
        # Apply before abbreviation expansions to unify downstream handling
        if debug_mode:
            # Prefer long form in debug outputs
            text = re.sub(r'^(?:U|UL)\.?\s+', 'JALAN ', text)
        else:
            # Prefer abbreviated 'JL.' in normal outputs
            text = re.sub(r'^(?:U|UL)\.?\s+', 'JL. ', text)

        # Normalize common person/street name OCR typos that appear in addresses
        # e.g., variations of HASYIM / H. ASYIM / HASYM -> HASYIM
        # Do this early so later tokenization/abbreviation handling sees the corrected tokens
        for pat, repl in NAME_TYPO_PATTERNS:
            text = re.sub(pat, repl, text)

        if debug_mode:
            # Expand to long forms and remove periods
            abbreviations = ABBREVIATIONS_DEBUG
            for pattern, replacement in abbreviations.items():
                text = re.sub(pattern, replacement, text)
            # Remove any remaining punctuation except spaces and slashes (drop periods)
            text = re.sub(r'[^A-Z0-9\s/]', ' ', text)
        else:
            # Keep traditional abbreviations with periods
            abbreviations = ABBREVIATIONS_NORMAL
            for pattern, replacement in abbreviations.items():
                text = re.sub(pattern, replacement, text)
            # Allow periods in output
            text = re.sub(r'[^A-Z0-9\s/\.]', ' ', text)
        
        # Collapse duplicate periods and tidy spacing like 'JL..' -> 'JL.' and 'NO..' -> 'NO.'
        text = re.sub(r'\.{2,}', '.', text)
        # Remove spaces before periods and ensure a single space after period when followed by a word/number
        text = re.sub(r'\s+\.', '.', text)
        text = re.sub(r'\.\s*', '. ', text)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Check if the address is too short or too long
        if not (self.min_address_length <= len(text) <= self.max_address_length):
            return None
            
        # If it looks like an address, return it
        if self._looks_like_address(text, context):
            return text
            
        return None
    
    def _looks_like_address(self, text: str, context: Optional[ParserContext] = None) -> bool:
        """Check if the text looks like an address.
        
        Args:
            text: The text to check
            context: Optional ParserContext for logging
            
        Returns:
            True if the text looks like an address, False otherwise
        """
        if not text or len(text) < self.min_address_length:
            self._log_debug(f"Text too short or empty: '{text}'", context)
            return False
            
        # Prepare uppercased text first
        text_upper = text.upper()
        # Skip header-like administrative lines unless they contain street cues
        header_admin = re.match(r'^(PROV(\.|INSI)?\s+|KAB(\.|UPATEN)?\s+|KOTA\s+|KOTAMADYA\s+)', text_upper)
        # Only real street cues can bypass header-admin filtering; RT/RW should not
        has_street_cue = any(cue in text_upper for cue in STREET_CUES)
        if (getattr(context, 'strict_admin_filter', True)) and header_admin and not has_street_cue:
            self._log_debug(f"Header/admin line without street cue, not an address: '{text}'", context)
            return False

        # Check for common address indicators
        for indicator in self.address_indicators:
            if indicator in text_upper:
                self._log_debug(f"Found address indicator '{indicator}' in text: '{text}'", context)
                return True
        
        # Check for common address patterns (e.g., "RT 01/02", "No. 123", "Blok A1")
        patterns = [
            (r'(NO\.?|NOMOR)\s*\d+', 'NO/NOMOR pattern'),
            (r'BLOK\s*[A-Z0-9]+', 'BLOK pattern'),
            (r'JL\.?\s+[A-Z]', 'JL pattern'),
            (r'JLN\.?\s+[A-Z]', 'JLN pattern'),
            (r'JALAN\s+[A-Z]', 'JALAN pattern'),
            (r'^[A-Z]+\.?\s+[A-Z0-9]+(?:\s+[A-Z0-9]+\.?)*$', 'Standard address format')
        ]
        
        for pattern, pattern_name in patterns:
            if re.search(pattern, text_upper):
                self._log_debug(f"Matched {pattern_name} in text: '{text}'", context)
                return True
            
        # Check for common address prefixes/suffixes (e.g., "KEL.", "KEC.", etc.)
        prefixes = [
            'KEL ', 'KEL. ', 'KELURAHAN ', 'DESA ', 'DS ', 'DS. ',
            'KEC ', 'KEC. ', 'KECAMATAN ',
            'KAB ', 'KAB. ', 'KABUPATEN ',
            'KOTA ', 'KOTAMADYA ',
        ]
        
        for prefix in prefixes:
            if text_upper.startswith(prefix):
                self._log_debug(f"Text starts with address prefix '{prefix}': '{text}'", context)
                return True
                
        # Special case for test data format "JL. CONTOH NO. 123"
        if re.match(r'^[A-Z]+\.?\s+[A-Z0-9]+(?:\s+[A-Z0-9]+\.?)*$', text_upper):
            self._log_debug(f"Matched standard address format: '{text}'", context)
            return True
            
        self._log_debug(f"Text does not appear to be an address: '{text}'", context)
        return False
    
    def _is_likely_false_positive(self, text: str) -> bool:
        """Check if the text is likely a false positive for an address."""
        if not text:
            return True
            
        text_lower = text.lower()
        
        # Skip lines that contain other field labels
        if any(term in text_lower for term in self.skip_terms):
            return True
            
        # Skip lines that are too short or too long
        if not (self.min_address_length <= len(text) <= self.max_address_length):
            return True
            
        # Skip lines that look like NIK or other numeric IDs
        if re.match(r'^\d+$', text.replace(' ', '')):
            return True
            
        return False
