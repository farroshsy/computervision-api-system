"""SIM (Surat Izin Mengemudi) extractor (minimal, accuracy-first).

Parses SIM OCR lines into structured fields with confidence and provenance.
Conservative: only returns fields when patterns are clear.
"""
from typing import Dict, Any, List, Optional, Tuple
import re

from app.models.schemas import ParserContext, make_document_result


class SIMExtractor:
    """Field-level extractor for SIM with conservative heuristics."""

    # Basic regexes (kept simple and conservative)
    _re_digits = re.compile(r"\b\d{12,18}\b")  # SIM number length varies; accept 12-18
    # New-format cards print the number grouped with dashes: 1427-8708-000059
    _re_dashed_number = re.compile(r"(?<!\d)(\d{4}[- ]\d{4}[- ]\d{6})(?!\d)")
    # Standalone bare date line, e.g. the unlabeled expiry on new-format cards
    _re_bare_date_line = re.compile(r"^\s*(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\s*$")
    _re_date = re.compile(r"\b(\d{1,2})[\-/](\d{1,2})[\-/](\d{2,4})\b")
    _re_blood = re.compile(r"\b(?:AB|A|B|O)[+-]?\b", re.IGNORECASE)
    # Canonical Indonesian SIM classes (real cards print Roman numerals: BI,
    # BII — never B1/B2; colloquial "B1"/"B2" and OCR 1/l-for-I confusions are
    # normalized to canonical form by _normalize_class).
    _class_tokens = {
        "A", "A UMUM",
        "BI", "BI UMUM", "BII", "BII UMUM",
        "C", "CI", "CII", "D", "DI",
    }
    # Class as written after 'SIM' (e.g. 'SIM BII UMUM'), OCR-tolerant
    _re_sim_class = re.compile(r"\bSIM\s+((?:A|B[I1l|]{1,2}|B2|C[I1l]{0,2}|D[I1l]?)(?:\s*UMUM)?)\b")

    def parse(self, context: ParserContext) -> Dict[str, Any]:
        if not context or not context.raw_lines:
            return make_document_result("SIM", {}, 0.0)

        lines = [l.strip() for l in context.raw_lines if l and l.strip()]
        fields: Dict[str, Any] = {}
        prov: Dict[str, Any] = {"method": "regex_minimal", "lines": len(lines)}

        # SIM Number (look for clear large digit sequence; avoid NIK-like if label says SIM)
        sim_no = self._extract_sim_number(lines)
        if sim_no:
            record = {"value": sim_no, "confidence": 0.9, "provenance": {"method": "sim_number_regex"}}
            fields["id_number"] = record
            # Backward-compat alias some tests expect
            fields["sim_number"] = record

        # Name (label-based)
        name = self._extract_by_label(lines, labels=("NAMA", "NAMA LENGKAP"))
        if name:
            fields["name"] = {"value": name, "confidence": 0.85, "provenance": {"method": "label_name"}}

        # Address (label-based; stop at admin-like cues)
        address = self._extract_by_label(lines, labels=("ALAMAT",))
        if address:
            fields["address"] = {"value": address, "confidence": 0.8, "provenance": {"method": "label_address"}}

        # Class (SIM class tokens)
        sim_class = self._extract_class(lines)
        if sim_class:
            fields["class"] = {"value": sim_class, "confidence": 0.85, "provenance": {"method": "class_tokens"}}

        # Blood type (if present with cue or standalone clear token)
        blood = self._extract_blood_type(lines)
        if blood:
            fields["blood_type"] = {"value": blood, "confidence": 0.9, "provenance": {"method": "blood_regex"}}

        # Validity dates
        v_from, v_to = self._extract_validity(lines)
        if v_from:
            fields["valid_from"] = {"value": v_from, "confidence": 0.8, "provenance": {"method": "date_regex_from"}}
        if v_to:
            rec_date = {"value": v_to, "confidence": 0.85, "provenance": {"method": "date_regex_to"}}
            fields["expiry_date"] = rec_date
            # Backward-compat alias expected by some tests
            fields["valid_to"] = rec_date

        # Derive overall confidence as median of provided field confidences
        if fields:
            confs = [v.get("confidence", 0.0) for v in fields.values()]
            overall = sorted(confs)[len(confs) // 2]
        else:
            overall = 0.0
        return make_document_result("SIM", fields, overall, prov)

    # ---------------- helpers -----------------

    def _extract_sim_number(self, lines: List[str]) -> Optional[str]:
        any_sim_cue = any("SIM" in ln.upper() or "MENGEMUDI" in ln.upper() or "DRIVING" in ln.upper() for ln in lines)
        # New-format dashed number is unambiguous — accept anywhere on the card
        for line in lines:
            m = self._re_dashed_number.search(line)
            if m:
                return m.group(1).replace(" ", "-")
        # Prefer lines containing 'SIM' near digits
        for line in lines:
            lu = line.upper()
            if "SIM" in lu:
                m = self._re_digits.search(lu)
                if m:
                    return m.group(0)
        # Fallback: only if the document contains any SIM cue at all
        if not any_sim_cue:
            return None
        for line in lines:
            m = self._re_digits.search(line)
            if m:
                return m.group(0)
        return None

    def _extract_by_label(self, lines: List[str], labels: Tuple[str, ...]) -> Optional[str]:
        # Accept bilingual labels like 'NAMA/NAME' or 'ALAMAT/ADDRESS' before colon
        base = "|".join(map(re.escape, labels))
        pattern = re.compile(r"^\s*(?:" + base + r")(?:\s*/\s*[A-Z ]+)?[\s:.-]*", re.IGNORECASE)
        for i, line in enumerate(lines):
            m = pattern.match(line)
            if not m:
                continue
            rem = line[m.end():].strip()
            if rem:
                return self._clean_simple(self._strip_bilingual_tail(rem))
            # next line fallback (single line only)
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt:
                    return self._clean_simple(self._strip_bilingual_tail(nxt))
        return None

    def _normalize_class(self, cand: str) -> Optional[str]:
        """Normalize a raw class candidate to canonical form (BI, BII UMUM, ...).

        Handles colloquial digits (B1 -> BI, B2 -> BII) and OCR confusions
        (1/l/| read for I). Returns None if not a valid class.
        """
        t = re.sub(r"\s+", " ", (cand or "").upper()).strip()
        if not t:
            return None
        umum = False
        if t.endswith("UMUM"):
            umum = True
            t = t[: -len("UMUM")].strip()
        # Fold OCR confusions inside the letter token
        t = t.replace("|", "I").replace("L", "I")
        # Colloquial digits: B1 -> BI, B2 -> BII; stray 1 read for I
        if t == "B2":
            t = "BII"
        t = t.replace("1", "I")
        base = t if not umum else f"{t} UMUM"
        return base if base in self._class_tokens else None

    def _extract_class(self, lines: List[str]) -> Optional[str]:
        # 1) label-based ('GOLONGAN'/'KELAS'), 2) inline 'SIM <class>',
        # 3) standalone class token on its own line (new-format cards print
        #    the class big next to the SIM number with no label) — accepted
        #    conservatively: only multi-char tokens or explicit UMUM variants,
        #    single letters need label context to avoid noise.
        for line in lines:
            lu = line.upper()
            m = re.search(r"\b(KELAS|GOLONGAN)\b[\s:.-]*([A-Z0-9|/ ]{1,9})", lu)
            if m:
                norm = self._normalize_class(m.group(2))
                if norm:
                    return norm
            m2 = self._re_sim_class.search(lu)
            if m2:
                norm = self._normalize_class(m2.group(1))
                if norm:
                    return norm
        for line in lines:
            token = re.sub(r"\s+", " ", line.upper()).strip()
            norm = self._normalize_class(token)
            if norm and (len(norm.replace(" UMUM", "")) >= 2 or norm.endswith("UMUM")):
                return norm
        return None

    def _extract_blood_type(self, lines: List[str]) -> Optional[str]:
        for line in lines:
            lu = line.upper()
            if re.search(r"\bGOL(ONGAN)?\b.*\bDARAH\b", lu):
                m = self._re_blood.search(lu)
                if m:
                    return m.group(0).upper()
        # Fallback: standalone if unambiguous context
        for line in lines:
            m = self._re_blood.fullmatch(line.strip())
            if m:
                return m.group(0).upper()
        return None

    def _extract_validity(self, lines: List[str]) -> Tuple[Optional[str], Optional[str]]:
        v_from: Optional[str] = None
        v_to: Optional[str] = None

        def norm(d):
            dd, mm, yy = d
            if len(yy) == 2:
                yy = ("20" + yy) if int(yy) < 50 else ("19" + yy)
            return f"{int(dd):02d}-{int(mm):02d}-{yy}"

        for line in lines:
            lu = line.upper()
            if re.search(r"(BERLAKU\s*(S/D|HINGGA|SAMPAI|S\.D\.)|MASA\s+BERLAKU|VALID\s+UNTIL)", lu):
                # try take the last date as 'to'
                dates = self._re_date.findall(lu)
                if dates:
                    if len(dates) == 1:
                        v_to = norm(dates[0])
                    else:
                        v_from = norm(dates[0])
                        v_to = norm(dates[-1])
        # New-format cards print the expiry as a bare unlabeled date
        # (bottom-right). Take the LATEST standalone bare-date line — issue
        # dates also appear but expiry is always the furthest in the future.
        if v_to is None:
            candidates = []
            for line in lines:
                m = self._re_bare_date_line.match(line)
                if m:
                    dd, mm, yyyy = m.groups()
                    try:
                        candidates.append((int(yyyy), int(mm), int(dd)))
                    except ValueError:
                        continue
            if candidates:
                y, mth, d = max(candidates)
                v_to = f"{d:02d}-{mth:02d}-{y}"
        return v_from, v_to

    def _clean_simple(self, text: str) -> str:
        # Minimal cleaner: condense spaces, strip trailing punctuation
        t = re.sub(r"\s+", " ", text).strip()
        t = re.sub(r"[\s,:;.-]+$", "", t)
        return t

    def _strip_bilingual_tail(self, text: str) -> str:
        # Remove residual bilingual label tail like '/Name : ' at the start of the value
        t = text.lstrip()
        t = re.sub(r"^/\s*[A-Za-z ]+\s*[:.-]*\s*", "", t)
        return t
