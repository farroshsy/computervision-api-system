"""STNK (Surat Tanda Nomor Kendaraan) extractor (minimal, accuracy-first)."""
from typing import Dict, Any, Optional, Tuple, List
import re

from app.models.schemas import ParserContext, make_document_result


class STNKExtractor:
    # Conservative patterns
    _re_plate = re.compile(r"\b([A-Z]{1,2})\s*(\d{1,4})\s*([A-Z]{1,3})\b")  # e.g., B 1234 XYZ
    _re_date = re.compile(r"\b(\d{1,2})[\-/](\d{1,2})[\-/](\d{2,4})\b")
    # Value shapes for fallback when labels are OCR-garbled
    _re_vin_shape = re.compile(r"\b(?=(?:[A-Z0-9]*\d){4})(?=(?:[^A-Z]*[A-Z]){2})[A-Z0-9]{15,17}\b")
    _re_engine_shape = re.compile(r"\b(?=(?:[A-Z0-9]*\d){4})(?=[A-Z0-9]*[A-Z])[A-Z0-9]{8,12}\b")

    def parse(self, context: ParserContext) -> Dict[str, Any]:
        if not context or not context.raw_lines:
            return make_document_result("STNK", {}, 0.0)

        lines = [l.strip() for l in context.raw_lines if l and l.strip()]
        fields: Dict[str, Any] = {}
        prov: Dict[str, Any] = {"method": "regex_minimal", "lines": len(lines)}

        plate = self._extract_plate(lines)
        if plate:
            fields["plate_number"] = {"value": plate, "confidence": 0.92, "provenance": {"method": "plate_regex"}}
            # schema-aligned key
            fields["nomor_polisi"] = {"value": plate, "confidence": 0.92, "provenance": {"method": "plate_regex"}}

        owner = self._extract_by_label(lines, ("NAMA", "NAMA PEMILIK"))
        if owner:
            fields["owner_name"] = {"value": owner, "confidence": 0.85, "provenance": {"method": "label_owner"}}
            # schema-aligned key
            fields["owner"] = {"value": owner, "confidence": 0.85, "provenance": {"method": "label_owner"}}

        address = self._extract_by_label(lines, ("ALAMAT",))
        if address:
            fields["address"] = {"value": address, "confidence": 0.8, "provenance": {"method": "label_address"}}
            # schema-aligned key
            fields["alamat"] = {"value": address, "confidence": 0.8, "provenance": {"method": "label_address"}}

        brand = self._extract_by_label(lines, ("MERK", "MEREK", "MERK/TYPE", "MERK/TIPE", "BRAND", "MERK & TIPE"))
        if brand:
            fields["brand"] = {"value": brand, "confidence": 0.8, "provenance": {"method": "label_brand"}}

        # An STNK prints TYPE and MODEL as two different rows: "FUSO FM 517 HRDK"
        # (the manufacturer's type code) and "BESTEL WG TRO" (the body/model the
        # customer's spec calls "Truck's type"). Reading TYPE into `model` put a
        # type code — and, via the plate regex, a fake plate — into both fields.
        model = self._extract_by_label(lines, ("MODEL",))
        if model:
            fields["model"] = {"value": model, "confidence": 0.75, "provenance": {"method": "label_model"}}

        tipe = self._extract_by_label(lines, ("TIPE", "TYPE"))
        if tipe:
            fields["tipe"] = {"value": tipe, "confidence": 0.75, "provenance": {"method": "label_tipe"}}

        year = self._extract_by_label(lines, ("TAHUN PEMBUATAN", "THN", "TAHUN"))
        if year and re.fullmatch(r"\d{4}", year):
            fields["year"] = {"value": year, "confidence": 0.85, "provenance": {"method": "label_year"}}

        vin = self._extract_by_label(lines, ("NOMOR RANGKA", "NO. RANGKA", "RANGKA", "VIN", "NO RANGKA"))
        if vin:
            fields["vin_chassis"] = {"value": vin, "confidence": 0.8, "provenance": {"method": "label_vin"}}
            # schema-aligned key
            fields["nomor_rangka"] = {"value": vin, "confidence": 0.8, "provenance": {"method": "label_vin"}}

        eng = self._extract_by_label(lines, ("NOMOR MESIN", "NO. MESIN", "MESIN", "NO MESIN"))
        if eng:
            fields["engine_number"] = {"value": eng, "confidence": 0.8, "provenance": {"method": "label_engine"}}
            # schema-aligned key
            fields["nomor_mesin"] = {"value": eng, "confidence": 0.8, "provenance": {"method": "label_engine"}}

        tax_to = self._extract_tax_valid_to(lines)
        if tax_to:
            fields["tax_valid_to"] = {"value": tax_to, "confidence": 0.85, "provenance": {"method": "tax_date"}}

        # Value-shape fallback when labels didn't survive OCR
        text = " ".join(l.upper() for l in lines)
        used = set()
        if "nomor_rangka" not in fields:
            m = self._re_vin_shape.search(text)
            if m:
                rec = {"value": m.group(0), "confidence": 0.7, "provenance": {"method": "vin_shape"}}
                fields["nomor_rangka"] = rec
                fields["vin_chassis"] = dict(rec)
                used.add(m.group(0))
        if "nomor_mesin" not in fields:
            for m in self._re_engine_shape.finditer(text):
                tok = m.group(0)
                if tok in used or any(tok in u for u in used):
                    continue
                # not a glued date like 13AUG2023 / 09022028
                if re.fullmatch(r"\d{1,2}[A-Z]{3,9}\d{4}", tok) or tok.isdigit():
                    continue
                rec = {"value": tok, "confidence": 0.6, "provenance": {"method": "engine_shape"}}
                fields["nomor_mesin"] = rec
                fields["engine_number"] = dict(rec)
                break

        # overall confidence
        if fields:
            confs = [v.get("confidence", 0.0) for v in fields.values()]
            overall = sorted(confs)[len(confs) // 2]
        else:
            overall = 0.0
        return make_document_result("STNK", fields, overall, prov)

    # ---------- helpers ----------
    def _extract_by_label(self, lines: List[str], labels: Tuple[str, ...]) -> Optional[str]:
        # Prefer the longest label to avoid partial matches (e.g., 'NAMA' vs
        # 'NAMA PEMILIK'). Spaces inside labels match zero-or-more whitespace
        # because OCR often glues them ("NAMAPEMILIK").
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

    def _extract_plate(self, lines: List[str]) -> Optional[str]:
        # The plate shape also matches the TYPE row ("FUSO FM 517 HRDK" ->
        # "FM 517 H"), so shape alone is not enough: take the first match whose
        # region code actually exists.
        from app.parser.spec_fields import plate_is_valid
        for line in lines:
            for m in self._re_plate.finditer(line.upper()):
                candidate = f"{m.group(1)} {m.group(2)} {m.group(3)}"
                if plate_is_valid(candidate):
                    return candidate
        return None

    def _extract_tax_valid_to(self, lines: List[str]) -> Optional[str]:
        for line in lines:
            lu = line.upper()
            if "PAJAK" in lu or "MASA BERLAKU" in lu or "BERLAKU" in lu:
                dates = self._re_date.findall(lu)
                if dates:
                    dd, mm, yy = dates[-1]
                    if len(yy) == 2:
                        yy = ("20" + yy) if int(yy) < 50 else ("19" + yy)
                    return f"{int(dd):02d}-{int(mm):02d}-{yy}"
        return None

    def _clean_simple(self, text: str) -> str:
        t = re.sub(r"\s+", " ", text).strip()
        # strip label punctuation from both ends (next-line values often
        # carry a leading ':' from the form layout)
        t = re.sub(r"^[\s,:;.-]+", "", t)
        t = re.sub(r"[\s,:;.-]+$", "", t)
        return t

