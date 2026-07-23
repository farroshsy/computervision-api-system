"""
NIK Extractor Module

This module contains the NIKExtractor class for extracting NIK (Nomor Induk Kependudukan)
from KTP documents.
"""

import re
from typing import Optional

from .base_extractor import FieldExtractor
from app.models.schemas import ParserContext

class NIKExtractor(FieldExtractor):
    """Extractor for NIK (Nomor Induk Kependudukan) field"""
    
    def __init__(self):
        super().__init__('nik')
        # Regex variants for noisy "NIK" label (e.g., N1K, N!K, NlK)
        # Accept T as mis-OCR for I (e.g., NTK)
        # Allow optional digit immediately after 'K' due to OCR artifacts like "NIK3"
        self.noisy_label = r'N[\W_\s]*[I1!l|T][\W_\s]*K\s*\d?'
        # Primary patterns (label-anchored and standalone digit runs)
        self.patterns = [
            # Label anchored with separators (colon/dot/hyphen/space)
            (rf'(?:{self.noisy_label})\s*[:\-\.]*\s*([A-Z0-9\s\-]{8,})', 1),
            # Standalone long digit runs: must begin after start or whitespace and start with a digit
            (r'(?:^|\s)(\d[\d\s\-]{14,}\d)(?!\d)', 1),
        ]
        # Character substitutions to recover digits from OCR confusions
        # Conservative substitutions: only digits-lookalikes that do not inflate counts
        # Avoid mapping letters to '1' (I/L/T/|) to prevent accidental 16-digit runs
        self.subs_map = str.maketrans({
            'O': '0', 'Q': '0', 'D': '0',
            'Z': '2',
            'S': '5',
            'B': '8',
            'G': '6',
        })
    
    def extract(self, context: ParserContext) -> Optional[str]:
        """Extract NIK using multiple patterns and strategies"""
        # Try each pattern on each line with substitution recovery
        partial_best: Optional[str] = None
        for i, line in enumerate(context.raw_lines):
            for pattern, group_idx in self.patterns:
                m = re.search(pattern, line, re.IGNORECASE)
                if not m:
                    continue
                segment = m.group(group_idx) if group_idx else m.group(0)
                candidate = self._recover_digits(segment)
                nik = self._first_valid_16(candidate)
                if nik:
                    self._log_extraction(context, nik, line_number=i, pattern=str(pattern))
                    return nik
                # track partial 14-15 digit sequences
                partial = self._best_partial_14_15(candidate)
                if partial:
                    partial_best = partial
        
        # If not found in raw_lines, try cleaned_lines
        if hasattr(context, 'cleaned_lines') and context.cleaned_lines:
            for i, line in enumerate(context.cleaned_lines):
                # Direct fast-path: exact label + 16 digits with optional separator
                m_direct = re.search(r'\bNIK\b\s*[:\-\.]?\s*(\d{16})\b', line, re.IGNORECASE)
                if m_direct:
                    nik = m_direct.group(1)
                    if self._is_valid_nik(nik):
                        self._log_extraction(context, nik, line_number=i, pattern='direct_label_16', source='cleaned_lines')
                        return nik
                for pattern, group_idx in self.patterns:
                    m = re.search(pattern, line, re.IGNORECASE)
                    if not m:
                        continue
                    segment = m.group(group_idx) if group_idx else m.group(0)
                    candidate = self._recover_digits(segment)
                    nik = self._first_valid_16(candidate)
                    if nik:
                        self._log_extraction(context, nik, line_number=i, pattern=str(pattern), source='cleaned_lines')
                        return nik
                    partial = self._best_partial_14_15(candidate)
                    if partial:
                        partial_best = partial
        
        # Special case: NIK on next line after noisy label (check both raw and cleaned lines)
        lines_to_check = [context.raw_lines]
        if hasattr(context, 'cleaned_lines') and context.cleaned_lines:
            lines_to_check.append(context.cleaned_lines)
            
        for lines in lines_to_check:
            for i, line in enumerate(lines):
                if re.search(self.noisy_label, line, re.IGNORECASE) and i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    candidate = self._recover_digits(next_line)
                    nik = self._first_valid_16(candidate)
                    if nik:
                        source = 'cleaned_lines' if lines is context.cleaned_lines else 'raw_lines'
                        self._log_extraction(context, nik, line_number=i+1, source=f'next_line_{source}', pattern='noisy_label_next_line')
                        return nik
                    partial = self._best_partial_14_15(candidate)
                    if partial:
                        partial_best = partial
        
        # Fallback: whole-document scan to recover a 16-digit run after substitutions
        try:
            joined = " \n ".join(context.raw_lines or [])
            # Remove noisy label tokens like 'NIK', 'NTK', optionally with a trailing single digit
            joined = re.sub(self.noisy_label, ' ', joined, flags=re.IGNORECASE)
            cand = self._recover_digits(joined)
            nik = self._first_valid_16(cand)
            if nik:
                self._log_extraction(context, nik, line_number=-1, source='whole_document')
                return nik
            # Try 17->16 slicing heuristic on whole-document compact digits
            nik_from_17 = self._nik_from_17_slice(cand)
            if nik_from_17:
                self._log_extraction(context, nik_from_17, line_number=-1, source='whole_document_17slice')
                return nik_from_17
        except Exception:
            pass

        # If we found a strong partial (14-15 digits), record it as auxiliary field
        if partial_best:
            try:
                provenance = {"source": type(self).__name__, "reason": "incomplete_digits"}
                context.add_field('partial_nik', partial_best, confidence=0.6, provenance=provenance)
                self._log_info(context, "Recorded partial_nik", value=partial_best)
            except Exception:
                pass
        else:
            # As a last resort, scan the whole document for 14-15 digit partials
            try:
                joined = " ".join(context.raw_lines or [])
                whole_partial = self._best_partial_14_15(self._recover_digits(joined))
                if whole_partial:
                    provenance = {"source": type(self).__name__, "reason": "incomplete_digits_whole_document"}
                    context.add_field('partial_nik', whole_partial, confidence=0.5, provenance=provenance)
                    self._log_info(context, "Recorded partial_nik from whole doc", value=whole_partial)
            except Exception:
                pass
        return None
    
    def _clean_nik(self, nik: str) -> str:
        """Legacy cleaner: translate common confusions and strip non-digits."""
        up = str(nik).upper().translate(self.subs_map)
        return re.sub(r'\D', '', up)
    
    def _recover_digits(self, text: str) -> str:
        """Apply OCR confusion substitutions and return only digits.
        Keeps spaces/dashes minimal for subsequent scanning.
        """
        if not text:
            return ''
        up = str(text).upper().translate(self.subs_map)
        # Keep digits, spaces and dashes for consecutive scanning
        return re.sub(r'[^0-9\s\-]', '', up)
    
    def _first_valid_16(self, text: str) -> Optional[str]:
        """Find a 16-digit run from a text containing digits/spaces/dashes.
        Prefer the last occurrence to avoid picking stray leading digits near the label.
        """
        if not text:
            return None
        # Collapse spaces/dashes
        compact = re.sub(r'[\s\-]+', '', text)
        # Scan for any 16 consecutive digits
        matches = re.findall(r'(\d{16})', compact)
        if not matches:
            return None
        nik = matches[-1]
        return nik if self._is_valid_nik(nik) else None

    def _nik_from_17_slice(self, text: str) -> Optional[str]:
        """If we have 17 consecutive digits, try plausible 16-digit slices.
        Conservative: only consider last or first 16 from a 17-run.
        """
        if not text:
            return None
        compact = re.sub(r'[\s\-]+', '', text)
        runs = re.findall(r'(\d{17})', compact)
        for run in runs[-3:]:  # check last few occurrences
            candidates = [run[:16], run[1:17]]
            for cand in candidates:
                if self._is_valid_nik(cand):
                    return cand
        return None

    def _best_partial_14_15(self, text: str) -> Optional[str]:
        """Return the last 14-15 digit run if present."""
        if not text:
            return None
        compact = re.sub(r'[\s\-]+', '', text)
        parts = re.findall(r'(\d{14,15})', compact)
        return parts[-1] if parts else None
    
    def _is_valid_nik(self, nik: str) -> bool:
        """Basic NIK validation (16 digits)"""
        return len(nik) == 16 and nik.isdigit()

# Backward compatibility: some tests/imports expect `NikExtractor`
# Keep alias to the canonical `NIKExtractor` class name
NikExtractor = NIKExtractor
