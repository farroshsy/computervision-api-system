"""
Address Extractor Module

This module contains the AddressExtractor class for extracting the address field from KTP documents.
"""

import re
from typing import Dict, List, Optional, Tuple

from .base_extractor import FieldExtractor
from app.models.schemas import ParserContext

class AddressExtractor(FieldExtractor):
    """Extractor for the address field in KTP documents"""
    
    def __init__(self):
        super().__init__('alamat')
        # Common OCR errors for 'Alamat' label
        self.address_labels = ["alamat", "alamal", "alamt", "alamet", "alamnt", "alamta", 
                             "aamat", "almat", "alama", "alamta", "alamata", "alamatt",
                             "alam", "almt", "alm", "alamt", "alama", "alamt", "alama",
                             "alamt", "alamat", "alamat", "alamat", "alamat", "alamat"]
        # Common address prefixes
        self.address_prefixes = [
            'JL', 'JLN', 'JALAN', 'GANG', 'GG', 'DS', 'DUSUN', 'DSN', 'RT', 'RW',
            'KAV', 'BLOK', 'NO', 'NOMOR', 'KEL', 'DESA', 'KEC', 'KAB', 'KOTA', 'PROV',
            'JALAN', 'JL', 'JLN', 'GANG', 'GG', 'DS', 'DUSUN', 'DESA', 'KELURAHAN',
            'KOMPLEK', 'KOMP', 'PERUMAHAN', 'PERUM', 'JL.', 'NO.', 'RT.', 'RW.'
        ]
        # Terms that indicate a line should be skipped
        self.skip_terms = [
            "nik", "nama", "tempat", "lahir", "jenis", "kelamin", "gol", "darah",
            "rt/rw", "rt rw", "kel/desa", "kecamatan", "agama", "pekerjaan", "status",
            "perkawinan", "kewarganegaraan", "berlaku", "hingga", "masa berlaku",
            "jenis kelamin", "tempat/tgl", "terpal", "tgilahir", "provinsi", "kabupaten"
        ]
        self.max_lines_to_check = 5
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract address using multiple patterns and strategies
        
        Args:
            context: ParserContext containing the document lines and extracted fields
            
        Returns:
            Optional[str]: Extracted address or None if not found
        """
        context.log_info(f"Starting {self.field_name} extraction")
        
        # Strategy 1: Try to find address using the address label with various patterns
        result = self._extract_by_label(context)
        if result:
            return result
            
        # Strategy 2: Try to find address after name field (common pattern)
        result = self._extract_after_name(context)
        if result:
            return result
            
        # Strategy 3: Look for standalone address patterns
        result = self._find_standalone_address(context)
        if result:
            return result
            
        context.log_info(f"Could not extract {self.field_name}")
        return None
        
    def _extract_by_label(self, context: ParserContext) -> Optional[str]:
        """Extract address by looking for label patterns."""
        for i, line in enumerate(context.raw_lines[:self.max_lines_to_check]):
            line_lower = line.lower()
            line_upper = line.upper()
            line_stripped = line.strip()
            
            # Skip lines that are too short or too long to be address labels
            if len(line_stripped) < 3 or len(line_stripped) > 100:
                continue
                
            # Check for address label in multiple ways
            label_found = False
            
            # 1. Check for exact label match
            for label in self.address_labels:
                if label == line_lower.strip(' :.-'):
                    label_found = True
                    break
                    
                # 2. Check if line starts with label followed by separator
                if line_lower.startswith(label) and line_lower[len(label):].strip().startswith((':', '-', '.')):
                    label_found = True
                    break
                    
                # 3. Check if line contains label (more lenient)
                if label in line_lower and len(line_lower) < 20:  # Short line with just label
                    label_found = True
                    break
            
            if label_found:
                context.log_info(f"Found address label at line {i}", line=line)
                
                # Get potential address lines following this label
                address_lines = self._get_potential_address_lines(context, i)
                if address_lines:
                    # Clean and join the address lines
                    address = self._clean_address_lines(address_lines, context)
                    if address:
                        return self._log_extraction(context, address, line_number=i, method="label")
        
        return None
        
    def _extract_after_name(self, context: ParserContext) -> Optional[str]:
        """Try to find address after the name field."""
        if "nama" not in context.extracted or not context.extracted["nama"]:
            return None
            
        name = context.extracted["nama"].upper()
        
        for i, line in enumerate(context.raw_lines):
            if name in line.upper() and i + 1 < len(context.raw_lines):
                    # Check next few lines for potential address
                    address_lines = self._get_potential_address_lines(context, i)
                    if address_lines:
                        address = self._clean_address_lines(address_lines, context)
                        if address:
                            return self._log_extraction(context, address, line_number=i, method="after_name")
                    break
        
        # If address not found with label, try to find standalone address
        standalone_address = self._find_standalone_address(context)
        if standalone_address:
            return self._log_extraction(context, standalone_address, method="standalone")
        
        # As a last resort, try to find any line that looks like an address
        for i, line in enumerate(context.raw_lines):
            line_upper = line.upper().strip()
            
            # Skip lines that are too short or too long
            if len(line_upper) < 10 or len(line_upper) > 100:
                continue
                
            # Skip lines that contain field labels or other non-address content
            if any(term in line_upper for term in ["NIK", "NAMA", "TEMPAT", "LAHIR", "JENIS KELAMIN"]):
                continue
                
            # Check if line starts with a common address prefix
            if any(line_upper.startswith(prefix) for prefix in self.address_prefixes):
                # Clean the line and check if it looks like a valid address
                cleaned_line = self._clean_address_line(line_upper, context)
                if cleaned_line and self._is_valid_address(cleaned_line, context):
                    return self._log_extraction(context, cleaned_line, line_number=i, method="fallback_prefix")
        
        return None
        # Second pass: Look for standalone address patterns
        return self._find_standalone_address(context)
    
    def _is_valid_address(self, text: str, context: Optional[ParserContext] = None) -> bool:
        """Check if text looks like a valid address
        
        Args:
            text: The text to validate
            context: Optional ParserContext for logging (not used in validation)
            
        Returns:
            bool: True if the text looks like a valid address
        """
        if not text or len(text) < 5:  # Minimum reasonable address length
            return False
            
        # Should not contain field labels or other non-address content
        if any(term in text.lower() for term in self.skip_terms):
            return False
            
        # Should not be just numbers or dates
        if re.search(r'^\d+$', text) or re.search(r'\d{2}[-/.]\d{2}[-/.]\d{2,4}', text):
            return False
            
        # Should contain some letters and at least one number (for house/street number)
        has_letters = any(c.isalpha() for c in text)
        has_numbers = any(c.isdigit() for c in text)
        
        # For very short addresses, be more lenient
        if len(text) < 10:
            return has_letters
            
        # For longer addresses, expect both letters and numbers
        return has_letters and has_numbers
    
    def _is_address_like(self, text: str) -> bool:
        """Check if the given text looks like an address.
        
        Args:
            text: The text to check
            
        Returns:
            bool: True if the text looks like an address, False otherwise
        """
        if not text:
            return False
            
        # Common address patterns
        address_indicators = [
            r'\b(?:JL|JLN|JALAN|GANG|GG|DS|DUSUN|DSN|RT|RW|NO|NOMOR|KEL|KELURAHAN|KEC|KECAMATAN|KAB|KABUPATEN|KOTA|PROV|PROVINSI)\b',
            r'\b(?:BLOK|BLOK\.|KAV|KAV\.|NO\.?\s*\d+)\b',
            r'\b(?:RT\.?\s*\d+|RW\.?\s*\d+)\b',
            r'\d+[A-Za-z]?\s*(?:\/|\\|\-)\s*\d+[A-Za-z]?',  # House numbers like 123/45 or 123-45
            r'^[A-Za-z\s]+\s+\d+[A-Za-z]?$'  # Street name followed by number
        ]
        
        # Check if any address pattern matches
        for pattern in address_indicators:
            if re.search(pattern, text, re.IGNORECASE):
                return True
                
        # Check for common address components
        if (any(word in text.upper() for word in ['JL', 'JLN', 'JALAN', 'GANG', 'NO', 'RT', 'RW', 'BLOK', 'KAV']) and 
            any(c.isdigit() for c in text)):
            return True
            
        # Check for address-like structure (letters, numbers, and common separators)
        if (any(c.isalpha() for c in text) and 
            any(c.isdigit() for c in text) and 
            any(sep in text for sep in [' ', ',', '.', '-', '/'])):
            return True
            
        return False
        
    def _get_potential_address_lines(self, context: ParserContext, label_line_num: int) -> List[str]:
        """Get potential address lines following a label.
        
        Args:
            context: ParserContext containing the document lines
            label_line_num: Line number where the label was found
            
        Returns:
            List of potential address lines
        """
        address_lines = []
        max_lines = min(label_line_num + 5, len(context.raw_lines))  # Look at next 4 lines
        
        for i in range(label_line_num + 1, max_lines):
            line = context.raw_lines[i].strip()
            
            # Skip empty lines or lines that are too short
            if not line or len(line) < 3:  # Reduced minimum length to catch short addresses
                continue
                
            line_lower = line.lower()
            line_upper = line.upper()
            
            # Skip lines that contain field labels or other non-address content
            if any(term in line_lower for term in self.skip_terms):
                # If we've already started collecting address lines, stop at the first skip
                if address_lines:
                    break
                continue
                
            # Check for RT/RW in the line
            rt_rw_match = re.search(r'\b(?:RT\s*[.:]?\s*(\d+))?\s*(?:RW\s*[.:]?\s*(\d+))?\b', 
                                 line, 
                                 flags=re.IGNORECASE)
                                  
            if rt_rw_match and (rt_rw_match.group(1) or rt_rw_match.group(2)):
                # If this line only contains RT/RW, add it and continue
                if re.sub(r'\b(?:RT|RW)\s*[.:]?\s*\d+\b', '', line, flags=re.IGNORECASE).strip() == '':
                    address_lines.append(line)
                    context.log_debug("Added RT/RW line to address", line_number=i, line_content=line)
                    continue
            
            # Check if line contains address-like patterns
            is_address_like = self._is_address_like(line_upper)
            
            # If we've already added some lines, check if this is a continuation
            if address_lines:
                prev_line = address_lines[-1]
                
                # Check for common continuation patterns
                is_continuation = (
                    is_address_like or  # Line looks like an address
                    re.match(r'^\d+', line) or  # Starts with number
                    any(line_upper.startswith(prefix) for prefix in ['NO', 'NOMOR', 'RT', 'RW', 'KAV', 'BLOK', 'JL', 'JLN', 'JALAN']) or
                    (len(line) > 5 and ' ' in line and any(c.isdigit() for c in line)) or  # Contains both letters and numbers
                    (len(line) > 10 and ' ' in line)  # Longer text with spaces
                )
                
                if is_continuation:
                    # If the previous line ends with a common address separator, append directly
                    if any(prev_line.rstrip().endswith(sep) for sep in [',', '.', '-', '/']):
                        address_lines[-1] = f"{prev_line.rstrip()} {line.lstrip()}"
                    else:
                        address_lines[-1] = f"{prev_line} {line}"
                    context.log_debug("Merged continuation line", 
                                   line_number=i,
                                   line_content=line,
                                   merged_line=address_lines[-1])
                    continue
            
            # If this line starts with common address prefixes, it's likely part of the address
            if any(line_upper.startswith(prefix) for prefix in self.address_prefixes):
                address_lines.append(line)
                context.log_debug("Added line with common address prefix", 
                               line_number=i,
                               line_content=line,
                               prefix=next((p for p in self.address_prefixes if line_upper.startswith(p)), None))
                continue
                
            # If we haven't added any lines yet, check if this could be the start of an address
            if not address_lines:
                # Check if this line looks like it could be an address
                has_letters = any(c.isalpha() for c in line)
                has_digits = any(c.isdigit() for c in line)
                has_space = ' ' in line
                line_len = len(line)
                
                # More precise address start detection
                is_likely_address = (
                    is_address_like or
                    (has_letters and has_digits and has_space) or  # Mixed content with numbers
                    (has_letters and has_space and line_len > 10) or  # Longer text with spaces
                    any(line_upper.startswith(prefix) for prefix in self.address_prefixes) or
                    (has_letters and has_digits and line_len > 15) or  # Longer mixed content
                    (has_letters and line_len > 20)  # Very long text line
                )
                
                if is_likely_address:
                    context.log_info("Starting address with line",
                                   line_number=i,
                                   line_content=line,
                                   reason="Matched address start pattern")
                    address_lines.append(line)
                    continue
            
            # If we've already started collecting address lines, check if this line
            # looks like a continuation (e.g., neighborhood/village name)
            if address_lines:
                is_continuation = (
                    (len(line) > 5 and ' ' in line) or  # Reasonable length with spaces
                    any(prefix in line_upper for prefix in ['RT', 'RW', 'KEL', 'DESA', 'KEC', 'KAB', 'KELURAHAN', 'KECAMATAN']) or
                    (any(c.isdigit() for c in line) and any(c.isalpha() for c in line)) or  # Mixed content
                    (line_upper == line and len(line.split()) <= 4)  # Short all-caps lines might be location names
                )
                
                if is_continuation:
                    context.log_debug("Adding continuation line to address",
                                   line_number=i,
                                   line_content=line)
                    address_lines.append(line)
                    continue
            
            # If we get here and haven't added any lines yet, this might not be an address
            if not address_lines and i - label_line_num > 2:  # Be more lenient with the first few lines
                context.log_debug("No address pattern matched, stopping search", 
                               line_number=i)
                break
            
        return address_lines
    
    def _clean_address_lines(self, lines: List[str], context: Optional[ParserContext] = None) -> str:
        """Clean and join multiple address lines
        
        Args:
            lines: List of address lines to clean and join
            context: Optional ParserContext for validation and logging
            
        Returns:
            str: Cleaned and joined address, or empty string if invalid
        """
        if not lines:
            if context:
                context.log_debug("No address lines to process")
            return ''
            
        cleaned_lines = []
        rt_rw_info = {'rt': None, 'rw': None}
        
        # Common OCR fixes mapping
        ocr_fixes = {
            '|': 'I',  # Common OCR error: I as |
            '1': 'I',  # Common OCR error: I as 1
            '0': 'O',  # Common OCR error: O as 0
            '5': 'S',  # Common OCR error: S as 5
            'BLOK': 'BLOK',
            'BLOK.': 'BLOK',
            'NO.': 'NO',
            'NO': 'NO',
            'N0': 'NO',  # Common OCR error: O as 0
            'NOMOR': 'NO',
            'NMR': 'NO',
            'RT.': 'RT',
            'RW.': 'RW',
            'JL.': 'JL',
            'JLN.': 'JLN',
            'JALAN': 'JL',
            'GANG': 'GG',
            'GG.': 'GG',
            'DS.': 'DS',
            'DUSUN': 'DS',
            'KEL.': 'KEL',
            'KELURAHAN': 'KEL',
            'KEC.': 'KEC',
            'KECAMATAN': 'KEC',
            'KAB.': 'KAB',
            'KABUPATEN': 'KAB',
            'KOTA': 'KOTA',
            'KOTA.': 'KOTA',
            'PROV.': 'PROV',
            'PROVINSI': 'PROV'
        }
        
        # First pass: extract RT/RW information and clean each line
        for line in lines:
            if not line or not line.strip():
                continue
                
            line_clean = re.sub(r'\s+', ' ', line.strip())
            
            # Log the original line for debugging
            if context and context.debug:
                context.log_debug("Processing address line", 
                               original=line, 
                               cleaned=line_clean)
            
            # Skip lines that look like other fields (NIK, Nama, etc.)
            field_pattern = r'^(NIK|Nama|Tempat/Tgl Lahir|Jenis Kelamin|Alamat|RT/RW|Kel/Desa|Kecamatan|Agama|Status Perkawinan|Pekerjaan|Kewarganegaraan|Berlaku Hingga|Gol\.? Darah|\d{16})[:.]?\s*$'
            if re.search(field_pattern, line_clean, re.IGNORECASE):
                if context and context.debug:
                    context.log_debug("Skipping field-like line", 
                                   line_content=line_clean)
                continue
            
            # Extract RT/RW information first (removes it from the line)
            line_clean, rt_rw_updated = self._extract_rt_rw(line_clean, rt_rw_info, context)
            
            # If the line only contained RT/RW info, skip to next line
            if rt_rw_updated and not line_clean.strip():
                continue
                
            # Clean and normalize the line
            line_clean = self._clean_address_line(line_clean, context)
            if line_clean:
                cleaned_lines.append(line_clean)
        
        # Second pass: join lines intelligently
        full_address = self._join_address_lines(cleaned_lines, context)
        
        # Add RT/RW information if found
        full_address = self._append_rt_rw(full_address, rt_rw_info, context)
        
        # Final cleanup and validation
        full_address = self._finalize_address(full_address, context)
        
        return full_address
        
    def _extract_rt_rw(self, line: str, rt_rw_info: Dict[str, Optional[str]], 
                      context: Optional[ParserContext] = None) -> Tuple[str, bool]:
        """Extract RT/RW information from a line
        
        Args:
            line: The line to process
            rt_rw_info: Dictionary to store extracted RT/RW info
            context: Optional ParserContext for logging
            
        Returns:
            Tuple of (cleaned_line, was_rt_rw_updated)
        """
        if not line:
            return line, False
            
        original_line = line
        rt_rw_updated = False
        
        # Handle RT/RW patterns: "RT 001 RW 002", "RT.001 RW.002", "RT: 001 RW: 002", etc.
        patterns = [
            # Combined RT and RW in one pattern (RT first)
            (r'(?i)(?:^|\b)(?:RT\s*[.:]?\s*(\d+))\s*(?:RW\s*[.:]?\s*(\d+))?\b', 2, False),
            # Combined RW and RT in one pattern (RW first)
            (r'(?i)(?:^|\b)(?:RW\s*[.:]?\s*(\d+))\s*(?:RT\s*[.:]?\s*(\d+))?\b', 2, False),
            # Individual RT
            (r'(?i)(?:^|\b)(RT)\s*[.:]?\s*(\d+)\b', 1, False),
            # Individual RW
            (r'(?i)(?:^|\b)(RW)\s*[.:]?\s*(\d+)\b', 1, False),
            # Just numbers that might be RT/RW (e.g., "001 002")
            (r'(?i)(?:^|\b)(\d{2,3})\s+(\d{2,3})\b', 2, True)
        ]
        
        # Add a sentinel at the end to handle the loop properly
        for pattern, expected_groups, is_numeric_only in patterns + [(None, 0, False)]:
            if pattern is None:
                break
                
            matches = list(re.finditer(pattern, line))
            if not matches:
                continue
                
            for match in reversed(matches):  # Process in reverse to not mess up string positions
                groups = match.groups()
                
                if is_numeric_only:
                    # Handle "001 002" format (RT 001 RW 002)
                    rt_num = groups[0].zfill(3)
                    rw_num = groups[1].zfill(3) if len(groups) > 1 and groups[1] else None
                    
                    if not any(c.isalpha() for c in line):  # Only if line is just numbers
                        if not rt_rw_info['rt']:
                            rt_rw_info['rt'] = f"RT {rt_num}"
                        if rw_num and not rt_rw_info['rw']:
                            rt_rw_info['rw'] = f"RW {rw_num}"
                        
                        line = line[:match.start()] + ' ' + line[match.end():]
                        rt_rw_updated = True
                        
                        if context and context.debug:
                            context.log_debug("Extracted RT/RW from numbers", 
                                           rt=rt_rw_info['rt'], 
                                           rw=rt_rw_info['rw'])
                else:
                    # Handle standard RT/RW patterns
                    rt_val = None
                    rw_val = None
                    
                    if expected_groups == 2 and len(groups) >= 2:
                        # Combined RT and RW
                        if 'rt' in match.group(0).lower() and 'rw' in match.group(0).lower():
                            rt_val = f"RT {groups[0].zfill(3)}" if groups[0] else None
                            rw_val = f"RW {groups[1].zfill(3)}" if len(groups) > 1 and groups[1] else None
                        # Just RT or RW with a number
                        elif len(groups) == 2 and groups[0] and groups[1]:
                            rt_or_rw = 'RT' if 'rt' in match.group(0).lower() else 'RW'
                            if rt_or_rw == 'RT':
                                rt_val = f"RT {groups[1].zfill(3)}"
                            else:
                                rw_val = f"RW {groups[1].zfill(3)}"
                    elif expected_groups == 1 and len(groups) >= 2:
                        # Single RT or RW
                        rt_or_rw = groups[0].upper()
                        num = groups[1].zfill(3) if groups[1] else None
                        
                        if rt_or_rw == 'RT' and num:
                            rt_val = f"RT {num}"
                        elif rt_or_rw == 'RW' and num:
                            rw_val = f"RW {num}"
                    
                    # Update RT/RW info if we found something
                    if rt_val and not rt_rw_info['rt']:
                        rt_rw_info['rt'] = rt_val
                        rt_rw_updated = True
                    if rw_val and not rt_rw_info['rw']:
                        rt_rw_info['rw'] = rw_val
                        rt_rw_updated = True
                    
                    if rt_rw_updated:
                        line = line[:match.start()] + ' ' + line[match.end():]
                        
                        if context and context.debug:
                            context.log_debug("Extracted RT/RW", 
                                           rt=rt_rw_info['rt'], 
                                           rw=rt_rw_info['rw'])
        
        # Clean up the line after RT/RW extraction
        line = re.sub(r'\s+', ' ', line).strip()
        
        if context and context.debug and rt_rw_updated:
            context.log_debug("After RT/RW extraction", 
# ... (rest of the code remains the same)
                           original=original_line, 
                           cleaned=line,
                           rt_rw_info=rt_rw_info)
        
        return line, rt_rw_updated
    
    def _clean_address_line(self, line: str, context: Optional[ParserContext] = None) -> str:
        """Clean and normalize a single address line
        
        Args:
            line: The line to clean
            context: Optional ParserContext for logging
            
        Returns:
            Cleaned line or empty string if invalid
        """
        if not line:
            return ''
            
        # Clean up common OCR errors and normalize
        line_clean = re.sub(r'\s+', ' ', line.strip())
        
        # Common replacements for address components
        replacements = [
            # Street types
            (r'\b(jl|jln|jlan|jln)\.?\s*', 'JALAN '),
            (r'\bjl\.?\s+', 'JALAN '),
            (r'\bjend\.?\s+', 'JENDERAL '),
            (r'\bgrogol\b', 'GROGOL'),
            (r'\bgang\b', 'GG'),
            
            # Numbering
            (r'\b(no|nomor?)\.?\s*(\d+)', r'NO \2'),
            (r'\b(no|nomor)\s+', 'NO '),
            (r'\b(blok|blk)\.?\s*(\w+)', r'BLOK \2'),
            (r'\b(kav|kav\.?|kaveling)\.?\s*(\w*)', 'KAV '),
            (r'\b(lt|lt\.?|lantai)\s*(\d+)\b', r'LT \2'),
            
            # Common address terms
            (r'\b(rt|rw)\.?\s*', r'\1'.upper() + ' '),
            (r'\b(kel|kel\.?|kelurahan)\s+(.+)', r'KELURAHAN \2'),
            (r'\b(desa|ds|ds\.?|des\.?)\s+(.+)', r'DESA \2'),
            (r'\b(kec|kec\.?|kecamatan)\s+(.+)', r'KECAMATAN \2'),
            (r'\b(kab|kab\.?|kabupaten)\s+(.+)', r'KABUPATEN \2'),
            (r'\b(kota)\s+(.+)', r'KOTA \2'),
            (r'\b(prov|prov\.?|provinsi)\s+(.+)', r'PROVINSI \2'),
            
            # Clean up any remaining special characters
            (r'[^\w\s.,/-]', ' '),
            
            # Normalize spaces
            (r'\s+', ' ')
        ]
        
        # Apply all replacements
        for pattern, repl in replacements:
            line_clean = re.sub(pattern, repl, line_clean, flags=re.IGNORECASE)
        
        # Final cleanup
        line_clean = line_clean.strip().upper()
        
        # Skip lines that are too short or don't look like addresses
        if (not line_clean or 
            len(line_clean) < 3 or 
            line_clean.replace(' ', '').isdigit() or
            re.search(r'^\d+$', line_clean)):
            return ''
            
        return line_clean
    
    def _join_address_lines(self, lines: List[str], context: Optional[ParserContext] = None) -> str:
        """Join multiple address lines into a single string
        
        Args:
            lines: List of address lines to join
            context: Optional ParserContext for logging
            
        Returns:
            Joined address string
        """
        if not lines:
            return ''
            
        # If there's only one line, return it as is
        if len(lines) == 1:
            return lines[0]
            
        # For multiple lines, join with commas and clean up
        full_address = ', '.join(line.strip() for line in lines if line.strip())
        
        # Clean up any double commas or spaces
        full_address = re.sub(r'\s*,\s*,', ',', full_address)
        full_address = re.sub(r'\s+', ' ', full_address).strip()
        
        # Remove any trailing commas
        full_address = re.sub(r',\s*$', '', full_address)
        
        return full_address
    
    def _append_rt_rw(self, address: str, rt_rw_info: Dict[str, Optional[str]], 
                     context: Optional[ParserContext] = None) -> str:
        """Append RT/RW information to the address if present
        
        Args:
            address: The base address
            rt_rw_info: Dictionary with RT/RW information
            context: Optional ParserContext for logging
            
        Returns:
            Address with RT/RW appended if available
        """
        if not address:
            return address
            
        rt = rt_rw_info.get('rt')
        rw = rt_rw_info.get('rw')
        
        if not rt and not rw:
            return address
            
        # Build the RT/RW string
        rt_rw_parts = []
        if rt:
            rt_rw_parts.append(rt)
        if rw:
            rt_rw_parts.append(rw)
            
        if not rt_rw_parts:
            return address
            
        rt_rw_str = ' '.join(rt_rw_parts)
        
        # Check if RT/RW is already in the address
        if rt and rt in address or (rw and rw in address):
            if context and context.debug:
                context.log_debug("RT/RW already in address", 
                               address=address,
                               rt_rw_info=rt_rw_info)
            return address
            
        # Append RT/RW to the address
        result = f"{address} {rt_rw_str}".strip()
        
        if context and context.debug:
            context.log_debug("Appended RT/RW to address",
                           original=address,
                           rt_rw_info=rt_rw_info,
                           result=result)
            
        return result
    
    def _finalize_address(self, address: str, context: Optional[ParserContext] = None) -> str:
        """Perform final cleanup and validation of the address
        
        Args:
            address: The address to finalize
            context: Optional ParserContext for logging
            
        Returns:
            Finalized address or empty string if invalid
        """
        if not address:
            return ''
            
        # Final cleanup
        address = re.sub(r'\s+', ' ', address).strip()
        
        # Validate the address
        if not self._is_valid_address(address, context):
            if context and context.debug:
                context.log_debug("Invalid address", address=address)
            return ''
            
        return address
        
        # Handle special cases for address formatting
        full_address = re.sub(r'\bNO\.?\s*KAV\.?\s*', 'KAV ', full_address, flags=re.IGNORECASE)  # Fix "NO. KAV" or "NO KAV" to just "KAV"
        full_address = re.sub(r'\bNO\s+NO\b', 'NO', full_address)  # Fix duplicate NO
        full_address = re.sub(r'\bNO\.?\s+(\d+)', r'NO \1', full_address)  # Standardize NO format
        
        # Remove any remaining special chars except those commonly used in addresses
        full_address = re.sub(r'[^\w\s.,/-]', ' ', full_address)
        
        # Normalize spaces and convert to uppercase
        full_address = re.sub(r'\s+', ' ', full_address).strip().upper()
        
        # Final validation
        if not self._is_valid_address(full_address, context):
            return ''
            
        return full_address
    
    def _should_skip_line(self, line: str, line_number: int, context: ParserContext) -> bool:
        """Determine if a line should be skipped when looking for address content
        
        Args:
            line: The line to check
            line_number: Line number for logging
            context: Parser context for logging
            
        Returns:
            bool: True if the line should be skipped, False otherwise
        """
        line_lower = line.lower()
        line_upper = line.upper()
        
        # Skip very short or very long lines
        if len(line.strip()) < 3 or len(line) > 100:
            context.log_debug("Skipping line - too short or too long",
                           line_number=line_number,
                           line_length=len(line))
            return True
            
        # Skip lines that match any skip terms as whole words
        if any(f' {term} ' in f' {line_lower} ' for term in self.skip_terms):
            context.log_debug("Skipping line with skip term",
                           line_number=line_number,
                           matched_term=next((t for t in self.skip_terms if t in line_lower), None))
            return True
            
        # Skip lines that contain common field patterns
        field_patterns = [
            r'^\s*(?:nik|nama|tempat\s+lahir|tgl\.?\s*lahir|jenis\s+kelamin|gol\.?\s*darah|alamat|rt/rw|kel/desa|kecamatan|status\s+perkawinan|pekerjaan|kewarganegaraan|berlaku\s+hingga|provinsi|kabupaten|kota)\s*[:.]',
            r'\b(?:nik|nama|tempat|lahir|jenis|kelamin|gol|darah|alamat|rt|rw|kel|desa|kecamatan|kabupaten|kota|provinsi|agama|pekerjaan|status|perkawinan|kewarganegaraan|berlaku|hingga)\b.*[0-9]',
            r'^\d{16}$',  # Just a NIK number
            r'^\d{2}[-/.]\d{2}[-/.]\d{2,4}',  # Dates
            r'^\s*\d+\s*$'  # Just a number
        ]
        
        if any(re.search(pattern, line, re.IGNORECASE) for pattern in field_patterns):
            context.log_debug("Skipping field-like line",
                           line_number=line_number,
                           pattern_matched=next((p for p in field_patterns if re.search(p, line, re.IGNORECASE)), None))
            return True
            
        # Skip lines that look like other document fields
        if any(field in line_upper for field in ['NIK', 'NAMA', 'TEMPAT/ TGL LAHIR', 'JENIS KELAMIN', 'GOL. DARAH', 'ALAMAT', 'RT/RW', 'KEL/DESA', 'KECAMATAN', 'AGAMA', 'STATUS PERKAWINAN', 'PEKERJAAN', 'KEWARGANEGARAAN', 'BERLAKU HINGGA']):
            context.log_debug("Skipping line with document field",
                           line_number=line_number,
                           matched_field=next((f for f in ['NIK', 'NAMA', 'TEMPAT/ TGL LAHIR', 'JENIS KELAMIN', 'GOL. DARAH', 'ALAMAT', 'RT/RW', 'KEL/DESA', 'KECAMATAN', 'AGAMA', 'STATUS PERKAWINAN', 'PEKERJAAN', 'KEWARGANEGARAAN', 'BERLAKU HINGGA'] if f in line_upper), None))
            return True
            
        # Skip lines that look like dates or NIKs
        if re.search(r'\d{2}[-/.]\d{2}[-/.]\d{2,4}', line) or re.search(r'\b\d{16}\b', line):
            context.log_debug("Skipping line with date or NIK",
                           line_number=line_number)
            return True
            
        return False

    def _find_standalone_address(self, context: ParserContext) -> Optional[str]:
        """Look for address patterns without a clear label
        
        Args:
            context: ParserContext containing the raw lines
            
        Returns:
            Optional[str]: Extracted address or None if not found
        """
        potential_addresses = []
        
        for i, line in enumerate(context.raw_lines):
            line_clean = re.sub(r'[^\w\s]', ' ', line).strip()
            
            # Skip lines that are too short or contain field labels
            if (len(line_clean) < 10 or 
                any(term in line_clean.lower() for term in self.skip_terms)):
                continue
                
            # Look for lines that might be addresses
            if (re.search(r'[A-Za-z]{3,}', line_clean) and  # Contains words
                not re.search(r'\d{8,}', line_clean.replace(' ', '')) and  # Not too many numbers
                not any(word in line_clean.lower() for word in ['nik', 'nama', 'tempat', 'lahir'])):
                
                # Clean and validate the potential address
                address = self._clean_address_lines([line_clean], context)
                if address:
                    potential_addresses.append((i, address))
        
        # If we found potential addresses, return the longest one
        if potential_addresses:
            # Sort by length (longest first) and return the first valid one
            potential_addresses.sort(key=lambda x: -len(x[1]))
            line_num, address = potential_addresses[0]
            self._log_extraction(context, address, line_number=line_num, pattern="standalone_pattern")
            return address
            
        return None