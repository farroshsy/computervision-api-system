"""KIR (Kendaraan Bermotor Uji Berkala) extractor (minimal, accuracy-first).

Parses KIR OCR lines into structured fields conservatively.
"""
from typing import Dict, Any, Optional, Tuple, List
import re

from app.models.schemas import ParserContext, make_document_result


class KIRExtractor:
    _re_date = re.compile(r"\b(\d{1,2})[\-/](\d{1,2})[\-/](\d{2,4})\b")
    # Real KIR cards print expiry with month names — Indonesian full names
    # ("26 JULI 2023") or English abbreviations ("13 AUG 2023"), depending on
    # the issuing office's system.
    _MONTHS = {
        "JANUARI": 1, "FEBRUARI": 2, "MARET": 3, "APRIL": 4, "MEI": 5,
        "JUNI": 6, "JULI": 7, "AGUSTUS": 8, "SEPTEMBER": 9, "OKTOBER": 10,
        "NOVEMBER": 11, "DESEMBER": 12,
        # Indonesian abbreviations
        "JAN": 1, "PEB": 2, "FEB": 2, "MAR": 3, "APR": 4,
        "JUN": 6, "JUL": 7, "AGU": 8, "AGT": 8, "SEP": 9, "SEPT": 9,
        "OKT": 10, "NOV": 11, "DES": 12,
        # English months/abbreviations seen on printed KIR cards
        # (SEPTEMBER/NOVEMBER spell the same in both languages)
        "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "MAY": 5, "JUNE": 6,
        "JULY": 7, "AUG": 8, "AUGUST": 8, "OCT": 10, "OCTOBER": 10,
        "DEC": 12, "DECEMBER": 12,
        # OCR confusions observed on real cards ("13AUC2023" = 13 AUG 2023)
        "AUC": 8,
    }
    # \s* not \s+: OCR often glues the whole date ("13AUC2023")
    _re_date_named = re.compile(
        r"\b(\d{1,2})\s*(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\s*(\d{4})\b",
        re.IGNORECASE,
    )
    # Value-shape patterns: KIR values keep distinctive shapes even when
    # their labels don't survive OCR (verified on real KYC photos).
    _re_vin_shape = re.compile(r"\b(?=(?:[A-Z0-9]*\d){4})(?=(?:[^A-Z]*[A-Z]){2})[A-Z0-9]{15,17}\b")
    _re_cert_shape = re.compile(r"\b[A-Z]{2,3}\d{4,6}[A-Z]?\b")
    _re_engine_shape = re.compile(r"\b(?=(?:[A-Z0-9]*\d){4})(?=[A-Z0-9]*[A-Z])[A-Z0-9]{8,12}\b")

    def parse(self, context: ParserContext) -> Dict[str, Any]:
        if not context or not context.raw_lines:
            return make_document_result("KIR", {}, 0.0)

        lines = [l.strip() for l in context.raw_lines if l and l.strip()]
        fields: Dict[str, Any] = {}
        prov: Dict[str, Any] = {"method": "regex_minimal", "lines": len(lines)}

        # Label variants match real "KARTU UJI BERKALA" cards: longer variants
        # first (sorted by len in _extract_by_label) so e.g. "NOMOR UJI
        # KENDARAAN : TBN5380" doesn't get sliced by the shorter "NOMOR UJI".
        cert = self._extract_by_label(lines, ("NOMOR UJI KENDARAAN", "NOMOR UJI", "NO. UJI", "NO UJI", "NOMOR KIR", "NO. KIR"))
        if cert:
            fields["certificate_number"] = {"value": cert, "confidence": 0.9, "provenance": {"method": "label_certificate"}}

        vehicle_id = self._extract_by_label(lines, ("NOMOR REGISTRASI KENDARAAN", "NOMOR KENDARAAN", "NO. KENDARAAN", "NO POLISI", "NOPOL", "PLAT", "NO. POLISI"))
        if vehicle_id:
            fields["vehicle_id"] = {"value": vehicle_id, "confidence": 0.85, "provenance": {"method": "label_vehicle"}}

        owner = self._extract_by_label(lines, ("NAMA PEMILIK",))
        if owner:
            fields["owner_name"] = {"value": owner, "confidence": 0.8, "provenance": {"method": "label_owner"}}

        issuer = self._extract_by_label(lines, ("DITERBITKAN OLEH", "DINAS PERHUBUNGAN", "PENERBIT", "PENGUJI"))
        if issuer:
            fields["issuer"] = {"value": issuer, "confidence": 0.7, "provenance": {"method": "label_issuer"}}

        # dates
        insp = self._extract_date_by_label(lines, ("TANGGAL UJI", "TGL UJI", "TANGGAL PEMERIKSAAN", "TGL PEMERIKSAAN"))
        if insp:
            fields["inspection_date"] = {"value": insp, "confidence": 0.8, "provenance": {"method": "label_date_insp"}}
            fields["tgl_uji"] = {"value": insp, "confidence": 0.8, "provenance": {"method": "label_date_insp"}}

        valid = self._extract_date_by_label(lines, ("MASA BERLAKU UJI BERKALA", "MASA BERLAKU UJI", "BERLAKU SAMPAI", "BERLAKU S/D", "MASA BERLAKU", "VALID S/D"))
        if valid:
            fields["valid_until"] = {"value": valid, "confidence": 0.85, "provenance": {"method": "label_date_valid"}}
            fields["masa_berlaku"] = {"value": valid, "confidence": 0.85, "provenance": {"method": "label_date_valid"}}

        # chassis and engine numbers if present on some KIR forms
        vin = self._extract_by_label(lines, ("NOMOR RANGKA KENDARAAN", "NOMOR RANGKA", "NO. RANGKA", "RANGKA", "VIN", "NO RANGKA"))
        if vin:
            fields["nomor_rangka"] = {"value": vin, "confidence": 0.8, "provenance": {"method": "label_vin"}}
        eng = self._extract_by_label(lines, ("NOMOR MOTOR PENGGERAK", "NOMOR MESIN", "NO. MESIN", "MESIN", "NO MESIN"))
        if eng:
            fields["nomor_mesin"] = {"value": eng, "confidence": 0.8, "provenance": {"method": "label_engine"}}

        # Logistics-planning fields (unique to KIR — no competitor extracts
        # these): payload capacity, gross weight, curb weight, vehicle info.
        # A dispatcher can answer "may this truck legally carry X kg?"
        daya = self._extract_by_label(lines, ("DAYA ANGKUT (ORANG/KG)", "DAYA ANGKUT"))
        if daya:
            fields["daya_angkut"] = {"value": daya, "confidence": 0.8, "provenance": {"method": "label_payload"}}
            m = re.search(r"(\d+)\s*ORANG\s*[/,]?\s*([\d.,]+)\s*KG", daya.upper())
            if m:
                fields["daya_angkut_orang"] = {"value": m.group(1), "confidence": 0.8, "provenance": {"method": "payload_parse"}}
                fields["daya_angkut_kg"] = {"value": m.group(2).replace(".", "").replace(",", ""), "confidence": 0.8, "provenance": {"method": "payload_parse"}}
        jbb = self._extract_by_label(lines, ("JBB/JBKB", "JBB / JBKB", "JBB"))
        if jbb:
            m = re.search(r"([\d.,]+)\s*KG", jbb.upper())
            if m:
                fields["jbb_kg"] = {"value": m.group(1).replace(".", "").replace(",", ""), "confidence": 0.8, "provenance": {"method": "label_jbb"}}
        berat = self._extract_by_label(lines, ("BERAT KOSONG KENDARAAN", "BERAT KOSONG"))
        if berat:
            m = re.search(r"([\d.,]+)", berat)
            if m:
                fields["berat_kosong_kg"] = {"value": m.group(1).replace(".", "").replace(",", ""), "confidence": 0.8, "provenance": {"method": "label_curb"}}
        merek = self._extract_by_label(lines, ("MEREK/TIPE", "MERK/TIPE", "MEREK / TIPE", "MERK / TIPE"))
        if merek:
            fields["merek_tipe"] = {"value": merek, "confidence": 0.8, "provenance": {"method": "label_brand"}}
        tahun = self._extract_by_label(lines, ("TAHUN PEMBUATAN/PERAKITAN", "TAHUN PEMBUATAN"))
        if tahun:
            m = re.search(r"(19|20)\d{2}", tahun)
            if m:
                fields["tahun_pembuatan"] = {"value": m.group(0), "confidence": 0.85, "provenance": {"method": "label_year"}}
        kelas = self._extract_by_label(lines, ("KELAS JALAN TERENDAH YANG BOLEH DILALUI", "KELAS JALAN TERENDAH", "KELAS JALAN"))
        if kelas:
            m = re.search(r"\b(I{1,3}|IV|V)\b", kelas.upper())
            if m:
                fields["kelas_jalan"] = {"value": m.group(1), "confidence": 0.8, "provenance": {"method": "label_road_class"}}

        # Fallbacks for garbled labels: distinctive value shapes + any
        # named-month date anywhere on the card (expiry is the only
        # month-name date printed on KIR)
        self._value_shape_fallback(lines, fields)
        if "valid_until" not in fields:
            for line in lines:
                m = self._re_date_named.search(line.upper())
                if m:
                    dd, month_name, yyyy = m.groups()
                    val = f"{int(dd):02d}-{self._MONTHS[month_name.upper()]:02d}-{yyyy}"
                    fields["valid_until"] = {"value": val, "confidence": 0.7, "provenance": {"method": "named_date_shape"}}
                    fields["masa_berlaku"] = dict(fields["valid_until"])
                    break

        if fields:
            confs = [v.get("confidence", 0.0) for v in fields.values()]
            overall = sorted(confs)[len(confs) // 2]
        else:
            overall = 0.0
        return make_document_result("KIR", fields, overall, prov)

    # ---------- helpers ----------
    def _value_shape_fallback(self, lines: List[str], fields: Dict[str, Any]) -> None:
        """Fill missing fields from value shapes when labels didn't survive OCR."""
        text = " ".join(l.upper() for l in lines)
        used: set = set()
        if "nomor_rangka" not in fields:
            m = self._re_vin_shape.search(text)
            if m:
                fields["nomor_rangka"] = {"value": m.group(0), "confidence": 0.7, "provenance": {"method": "vin_shape"}}
                used.add(m.group(0))
        if "certificate_number" not in fields:
            m = self._re_cert_shape.search(text)
            if m and m.group(0) not in used:
                fields["certificate_number"] = {"value": m.group(0), "confidence": 0.65, "provenance": {"method": "cert_shape"}}
                used.add(m.group(0))
        if "nomor_mesin" not in fields:
            for m in self._re_engine_shape.finditer(text):
                tok = m.group(0)
                # engine must not be (part of) the chassis/cert number and
                # must not be a glued date ("13AUC2023" fits the shape)
                if tok in used or any(tok in u for u in used):
                    continue
                if self._re_date_named.search(tok):
                    continue
                fields["nomor_mesin"] = {"value": tok, "confidence": 0.6, "provenance": {"method": "engine_shape"}}
                break

    def _extract_by_label(self, lines: List[str], labels: Tuple[str, ...]) -> Optional[str]:
        # Allow OCR-glued labels ("NAMAPEMILIK"): spaces inside a label
        # match zero-or-more whitespace
        ordered = tuple(sorted(labels, key=len, reverse=True))
        alts = "|".join(re.escape(lbl).replace(re.escape(" "), r"\s*") for lbl in ordered)
        pat = re.compile(r"^\s*(" + alts + r")[\s:.-]*", re.IGNORECASE)
        for i, line in enumerate(lines):
            m = pat.match(line)
            if not m:
                continue
            rem = line[m.end():].strip()
            if rem:
                return self._clean_simple(rem)
            if i + 1 < len(lines):
                nxt = lines[i + 1].strip()
                if nxt:
                    return self._clean_simple(nxt)
        return None

    def _extract_date_by_label(self, lines: List[str], labels: Tuple[str, ...]) -> Optional[str]:
        ordered = tuple(sorted(labels, key=len, reverse=True))
        alts = "|".join(re.escape(lbl).replace(re.escape(" "), r"\s*") for lbl in ordered)
        pat = re.compile(r"^\s*(" + alts + r")[\s:.-]*", re.IGNORECASE)
        for i, line in enumerate(lines):
            m = pat.match(line)
            if not m:
                continue
            part = line[m.end():]
            d = self._norm_first_date(part)
            if d:
                return d
            if i + 1 < len(lines):
                d2 = self._norm_first_date(lines[i + 1])
                if d2:
                    return d2
        return None

    def _norm_first_date(self, text: str) -> Optional[str]:
        t = text.strip()
        m = self._re_date.search(t)
        if m:
            dd, mm, yy = m.groups()
            if len(yy) == 2:
                yy = ("20" + yy) if int(yy) < 50 else ("19" + yy)
            return f"{int(dd):02d}-{int(mm):02d}-{yy}"
        # Indonesian month-name format as printed on real cards: 26 JULI 2023
        m2 = self._re_date_named.search(t)
        if m2:
            dd, month_name, yyyy = m2.groups()
            mm = self._MONTHS[month_name.upper()]
            return f"{int(dd):02d}-{mm:02d}-{yyyy}"
        return None

    def _clean_simple(self, text: str) -> str:
        t = re.sub(r"\s+", " ", text).strip()
        # strip label punctuation from both ends (next-line values often
        # carry a leading ':' from the form layout)
        t = re.sub(r"^[\s,:;.-]+", "", t)
        t = re.sub(r"[\s,:;.-]+$", "", t)
        return t
