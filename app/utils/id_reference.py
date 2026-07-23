"""Indonesian document reference data and cross-validation.

Most fields on Indonesian identity documents are closed vocabularies
(provinces, religions, marital statuses, ...). OCR output can be
fuzzy-corrected against these lexicons, and the NIK is self-validating:
digits 1-6 encode the issuing region (province/kabupaten/kecamatan codes)
and digits 7-12 encode the holder's birthdate (day +40 for women).

All corrections are conservative: a value is only replaced when it is a
close match to exactly one lexicon entry, never invented.
"""
import csv
import difflib
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_REGIONS_CSV = Path(__file__).resolve().parent.parent / "data" / "id_regions.csv"

# 38 provinces (post-2022 expansion, incl. new Papua provinces)
PROVINCES: List[str] = [
    "ACEH", "SUMATERA UTARA", "SUMATERA BARAT", "RIAU", "JAMBI",
    "SUMATERA SELATAN", "BENGKULU", "LAMPUNG", "KEPULAUAN BANGKA BELITUNG",
    "KEPULAUAN RIAU", "DKI JAKARTA", "JAWA BARAT", "JAWA TENGAH",
    "DI YOGYAKARTA", "JAWA TIMUR", "BANTEN", "BALI", "NUSA TENGGARA BARAT",
    "NUSA TENGGARA TIMUR", "KALIMANTAN BARAT", "KALIMANTAN TENGAH",
    "KALIMANTAN SELATAN", "KALIMANTAN TIMUR", "KALIMANTAN UTARA",
    "SULAWESI UTARA", "SULAWESI TENGAH", "SULAWESI SELATAN",
    "SULAWESI TENGGARA", "GORONTALO", "SULAWESI BARAT", "MALUKU",
    "MALUKU UTARA", "PAPUA", "PAPUA BARAT", "PAPUA SELATAN",
    "PAPUA TENGAH", "PAPUA PEGUNUNGAN", "PAPUA BARAT DAYA",
]

# BPS province codes as used in NIK digits 1-2
NIK_PROVINCE_CODES: Dict[str, str] = {
    "11": "ACEH", "12": "SUMATERA UTARA", "13": "SUMATERA BARAT",
    "14": "RIAU", "15": "JAMBI", "16": "SUMATERA SELATAN",
    "17": "BENGKULU", "18": "LAMPUNG", "19": "KEPULAUAN BANGKA BELITUNG",
    "21": "KEPULAUAN RIAU", "31": "DKI JAKARTA", "32": "JAWA BARAT",
    "33": "JAWA TENGAH", "34": "DI YOGYAKARTA", "35": "JAWA TIMUR",
    "36": "BANTEN", "51": "BALI", "52": "NUSA TENGGARA BARAT",
    "53": "NUSA TENGGARA TIMUR", "61": "KALIMANTAN BARAT",
    "62": "KALIMANTAN TENGAH", "63": "KALIMANTAN SELATAN",
    "64": "KALIMANTAN TIMUR", "65": "KALIMANTAN UTARA",
    "71": "SULAWESI UTARA", "72": "SULAWESI TENGAH",
    "73": "SULAWESI SELATAN", "74": "SULAWESI TENGGARA",
    "75": "GORONTALO", "76": "SULAWESI BARAT", "81": "MALUKU",
    "82": "MALUKU UTARA", "91": "PAPUA", "92": "PAPUA BARAT",
    "93": "PAPUA SELATAN", "94": "PAPUA TENGAH", "95": "PAPUA PEGUNUNGAN",
    "96": "PAPUA BARAT DAYA",
}

# Closed field vocabularies on KTP
AGAMA: List[str] = ["ISLAM", "KRISTEN", "KATOLIK", "HINDU", "BUDDHA", "KHONGHUCU"]
JENIS_KELAMIN: List[str] = ["LAKI-LAKI", "PEREMPUAN"]
STATUS_PERKAWINAN: List[str] = ["BELUM KAWIN", "KAWIN", "CERAI HIDUP", "CERAI MATI"]
KEWARGANEGARAAN: List[str] = ["WNI", "WNA"]

# Vehicle makes as printed in the STNK MERK field — the Indonesian
# commercial fleet is dominated by these; OCR one-char slips (USUZU,
# DATHATSU) correct cleanly against a closed list
VEHICLE_BRANDS: List[str] = [
    "TOYOTA", "DAIHATSU", "MITSUBISHI", "SUZUKI", "HONDA", "ISUZU",
    "HINO", "NISSAN", "FUSO", "MERCEDES BENZ", "VOLVO", "SCANIA",
    "MAN", "UD TRUCKS", "YAMAHA", "KIA", "HYUNDAI", "WULING", "FAW",
    "DONGFENG", "TATA", "MAZDA", "CHEVROLET", "FORD",
]

_KECAMATAN_CSV = Path(__file__).resolve().parent.parent / "data" / "id_kecamatan.csv"


@lru_cache(maxsize=1)
def kecamatan_names() -> List[str]:
    """All 7,285 kecamatan names (Kepmendagri 2025). Empty if file absent."""
    names = set()
    try:
        with open(_KECAMATAN_CSV, encoding="utf-8") as fh:
            reader = csv.reader(fh)
            next(reader, None)
            for row in reader:
                if len(row) >= 2 and row[1].strip():
                    names.add(row[1].strip().upper())
    except OSError:
        pass
    return sorted(names)

@lru_cache(maxsize=1)
def _load_regions() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Load Permendagri region codes from app/data/id_regions.csv.

    Returns (province_by_code, kabupaten_by_code) where kabupaten codes are
    4 digits without the dot ("1101" -> "KAB. ACEH SELATAN"). Empty dicts if
    the data file is missing — all kabupaten-level features then degrade
    silently to province-level behaviour.
    """
    provinces: Dict[str, str] = {}
    kabupaten: Dict[str, str] = {}
    try:
        with open(_REGIONS_CSV, encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if not row or row[0].startswith("#") or len(row) < 2:
                    continue
                code, name = row[0].strip(), row[1].strip().upper()
                if re.fullmatch(r"\d{2}", code):
                    provinces[code] = name
                elif re.fullmatch(r"\d{2}\.\d{2}", code):
                    kabupaten[code.replace(".", "")] = name
    except OSError:
        pass
    return provinces, kabupaten


@lru_cache(maxsize=1)
def kabupaten_names() -> List[str]:
    """Kabupaten/kota names cleaned for gazetteer matching (no KAB./KOTA prefixes).

    Used to correct tempat_lahir, which prints the bare region name.
    """
    _, kab = _load_regions()
    names = set()
    for name in kab.values():
        # Strip KABUPATEN/KAB./KOTA prefix and optional ADMINISTRASI/ADM.
        cleaned = re.sub(
            r"^(?:KABUPATEN|KAB\.?|KOTA)(?:\s+ADM(?:INISTRASI|\.)?)?\s+", "", name.strip()
        ).strip()
        if cleaned:
            names.add(cleaned)
    return sorted(names)


# Field key -> (lexicon provider, cutoff), applied by fuzzy_correct_fields.
# tempat_lahir uses a stricter cutoff: it may legitimately be a kecamatan or
# foreign city not in the kabupaten gazetteer — correct, never reject.
_FIELD_LEXICONS: Dict[str, List[str]] = {
    "agama": AGAMA,
    "jenis_kelamin": JENIS_KELAMIN,
    "status_perkawinan": STATUS_PERKAWINAN,
    "kewarganegaraan": KEWARGANEGARAAN,
    "provinsi": PROVINCES,
    "brand": VEHICLE_BRANDS,
}
# 0.80 = one OCR error per 5 chars; the runner-up margin guard in
# fuzzy_correct handles ambiguity between similar city names
_FIELD_CUTOFFS: Dict[str, float] = {"tempat_lahir": 0.80, "kecamatan": 0.80}


def fuzzy_correct(value: Optional[str], lexicon: List[str], cutoff: float = 0.75) -> Optional[str]:
    """Return the lexicon entry closest to value, or None if nothing close.

    Exact matches return immediately; otherwise difflib ratio must beat
    cutoff and the best match must be unambiguous.
    """
    if not value:
        return None
    v = re.sub(r"\s+", " ", value.upper().strip())
    if v in lexicon:
        return v
    matches = difflib.get_close_matches(v, lexicon, n=2, cutoff=cutoff)
    if len(matches) >= 1:
        # Unambiguous when single match, or clearly closer than runner-up
        if len(matches) == 1:
            return matches[0]
        r0 = difflib.SequenceMatcher(None, v, matches[0]).ratio()
        r1 = difflib.SequenceMatcher(None, v, matches[1]).ratio()
        if r0 - r1 > 0.05:
            return matches[0]
    return None


def repair_nik_from_printed_dob(fields: Dict) -> Dict:
    """Repair NIK digits 7-12 from the printed birthdate — ONLY when the
    NIK's own date segment is IMPOSSIBLE (month 27 does not exist), which
    proves an OCR misread. Both fields print the same fact; the readable
    one wins. Never touches a NIK whose segment is a valid date."""
    nik_rec = fields.get("nik")
    nik = str((nik_rec.get("value") if isinstance(nik_rec, dict) else nik_rec) or "")
    digits = re.sub(r"\D", "", nik)
    if len(digits) != 16:
        return fields
    dd = int(digits[6:8])
    female = dd > 40
    dd_real = dd - 40 if female else dd
    mm = int(digits[8:10])
    import datetime
    segment_valid = True
    try:
        datetime.date(2000, mm, dd_real)
    except ValueError:
        segment_valid = False
    if segment_valid:
        return fields
    dob_rec = fields.get("tanggal_lahir")
    dob = str((dob_rec.get("value") if isinstance(dob_rec, dict) else dob_rec) or "")
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", dob) or re.search(r"(\d{2})-(\d{2})-(\d{4})", dob)
    if not m:
        return fields
    g = m.groups()
    yyyy, p_mm, p_dd = (g[0], g[1], g[2]) if len(g[0]) == 4 else (g[2], g[1], g[0])
    try:
        datetime.date(int(yyyy), int(p_mm), int(p_dd))
    except ValueError:
        return fields
    new_dd = int(p_dd) + (40 if female else 0)
    repaired = digits[:6] + f"{new_dd:02d}{int(p_mm):02d}{int(yyyy) % 100:02d}" + digits[12:]
    if isinstance(nik_rec, dict):
        nik_rec["value"] = repaired
        prov = nik_rec.setdefault("provenance", {})
        if isinstance(prov, dict):
            prov["nik_repaired_from_dob"] = nik
    else:
        fields["nik"] = repaired
    return fields


def derive_dob_from_nik(fields: Dict) -> Dict:
    """Fill tanggal_lahir from the NIK's birthdate segment when the
    printed date is missing or unreadable.

    The NIK is the better-read field (large, digits-only); digits 7-12
    ARE the birthdate. A readable printed date always wins — when both
    exist and disagree, nik_cross_check flags it instead. Derived values
    carry provenance {"method": "derived_from_nik"}.
    """
    existing = fields.get("tanggal_lahir")
    existing_val = existing.get("value") if isinstance(existing, dict) else existing
    if isinstance(existing_val, str) and re.search(
            r"\d{1,2}[-/ ]\d{1,2}[-/ ]\d{4}|\d{4}[-/ ]\d{1,2}[-/ ]\d{1,2}", existing_val):
        return fields
    nik = fields.get("nik")
    info = nik_structure_info(nik.get("value") if isinstance(nik, dict) else nik)
    if not info:
        return fields
    import datetime
    today = datetime.date.today()
    yy = info["dob_yy"]
    # KTP holders are 17+: two-digit years newer than (current-17) are 19xx
    century = 2000 if yy <= (today.year - 17) % 100 else 1900
    try:
        dob = datetime.date(century + yy, info["dob_mm"], info["dob_dd"])
    except ValueError:
        return fields  # misread NIK digits — never invent an impossible date
    if dob > today:
        return fields
    fields["tanggal_lahir"] = {
        "value": dob.strftime("%d-%m-%Y"),
        "confidence": 0.75,
        "provenance": {"method": "derived_from_nik"},
    }
    return fields


def fuzzy_correct_fields(fields: Dict) -> Dict:
    """In-place lexicon correction of known closed-vocabulary fields.

    Also derives tanggal_lahir from the NIK when the printed date is
    unreadable (see derive_dob_from_nik).
    Only replaces a value when fuzzy_correct finds a confident match;
    otherwise the OCR value is left untouched.
    """
    repair_nik_from_printed_dob(fields)
    derive_dob_from_nik(fields)
    lexicons: Dict[str, List[str]] = dict(_FIELD_LEXICONS)
    kab = kabupaten_names()
    if kab:
        lexicons["tempat_lahir"] = kab
    kec = kecamatan_names()
    if kec:
        lexicons["kecamatan"] = kec
    for key, lexicon in lexicons.items():
        v = fields.get(key)
        raw = v.get("value") if isinstance(v, dict) else v
        if not isinstance(raw, str) or not raw.strip():
            continue
        corrected = fuzzy_correct(raw, lexicon, cutoff=_FIELD_CUTOFFS.get(key, 0.75))
        if corrected is None and key in ("tempat_lahir", "kecamatan"):
            # OCR often glues trailing garbage onto the place name
            # ("GARUT I -OS-I S" = GARUT + misread birthdate) — an exact
            # gazetteer hit on the leading word(s) rescues it
            words = re.findall(r"[A-Z]{2,}", raw.upper())
            for k in (2, 1):
                cand = " ".join(words[:k])
                if len(words) >= k and len(cand) >= 4 and cand in lexicon:
                    corrected = cand
                    break
        if corrected and corrected != raw.upper().strip():
            if isinstance(v, dict):
                fields[key]["value"] = corrected
                prov = fields[key].setdefault("provenance", {})
                if isinstance(prov, dict):
                    prov["lexicon_corrected_from"] = raw
            else:
                fields[key] = {"value": corrected, "confidence": 0.9,
                               "provenance": {"lexicon_corrected_from": raw}}

    # KTP header city ("KABUPATEN PAJURUAN"): the gazetteer holds BARE names,
    # so strip the KABUPATEN/KOTA prefix, correct the name, keep the prefix.
    # Kabupaten/kota is a closed vocabulary — a one-char OCR slip that lands a
    # WRONG-but-plausible city in a KYC record is exactly the dangerous bucket.
    if kab:
        v = fields.get("kota")
        raw = (v.get("value") if isinstance(v, dict) else v)
        if isinstance(raw, str) and raw.strip():
            m = re.match(r"^\s*(KABUPATEN|KOTA(?:\s+ADMINISTRASI)?|KAB\.?)\s+(.+)$",
                         raw.upper().strip())
            prefix, name = (m.group(1), m.group(2).strip()) if m else ("", raw.upper().strip())
            fixed = fuzzy_correct(name, kab, cutoff=0.80)
            if fixed and fixed != name:
                new_val = (prefix + " " + fixed).strip()
                if isinstance(v, dict):
                    v["value"] = new_val
                    prov = v.setdefault("provenance", {})
                    if isinstance(prov, dict):
                        prov["lexicon_corrected_from"] = raw
                else:
                    fields["kota"] = {"value": new_val, "confidence": 0.9,
                                      "provenance": {"lexicon_corrected_from": raw}}
    return fields


def nik_structure_info(nik: Optional[str]) -> Dict:
    """Decode NIK structure: region validity and encoded birthdate.

    Returns {} when nik is not 16 digits. Otherwise:
      - province_code, province_name (None if unknown code)
      - dob_dd, dob_mm, dob_yy (ints; dd already reduced if female +40)
      - is_female (bool, from the +40 day convention)
    """
    digits = re.sub(r"\D", "", nik or "")
    if len(digits) != 16:
        return {}
    prov_code = digits[0:2]
    kab_code = digits[0:4]
    _, kab_by_code = _load_regions()
    dd = int(digits[6:8])
    is_female = dd > 40
    if is_female:
        dd -= 40
    return {
        "province_code": prov_code,
        "province_name": NIK_PROVINCE_CODES.get(prov_code),
        "kabupaten_code": kab_code,
        # None when the regions data file is absent OR the code is unknown;
        # callers must distinguish via kab_by_code truthiness if needed
        "kabupaten_name": kab_by_code.get(kab_code) if kab_by_code else None,
        "dob_dd": dd,
        "dob_mm": int(digits[8:10]),
        "dob_yy": int(digits[10:12]),
        "is_female": is_female,
    }


def nik_cross_check(fields: Dict) -> List[str]:
    """Cross-validate NIK-encoded facts against other extracted KTP fields.

    Returns advisory reason codes (empty list = no inconsistency found):
      - nik_region_code_unknown: NIK digits 1-2 are not a province code
      - nik_dob_mismatch: NIK birthdate segment != extracted tanggal_lahir
      - nik_gender_mismatch: NIK +40-day convention != extracted jenis_kelamin
    Checks only run when both sides are confidently present.
    """
    reasons: List[str] = []

    def val(key: str) -> Optional[str]:
        v = fields.get(key)
        raw = v.get("value") if isinstance(v, dict) else v
        return raw if isinstance(raw, str) and raw.strip() else None

    info = nik_structure_info(val("nik"))
    if not info:
        return reasons

    if info["province_name"] is None:
        reasons.append("nik_region_code_unknown")
    else:
        # Kabupaten-level check only when the gazetteer is loaded; new
        # post-2019 kabupaten codes may be absent — advisory only
        _, kab_by_code = _load_regions()
        if kab_by_code and info["kabupaten_name"] is None:
            reasons.append("nik_kabupaten_code_unknown")

    dob = val("tanggal_lahir")
    if dob:
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", dob) or re.search(r"(\d{2})-(\d{2})-(\d{4})", dob)
        if m:
            g = m.groups()
            yyyy, mm, dd = (g[0], g[1], g[2]) if len(g[0]) == 4 else (g[2], g[1], g[0])
            if (int(dd) != info["dob_dd"] or int(mm) != info["dob_mm"]
                    or int(yyyy) % 100 != info["dob_yy"]):
                reasons.append("nik_dob_mismatch")

    gender = val("jenis_kelamin")
    if gender:
        g_up = gender.upper()
        if "PEREMPUAN" in g_up and not info["is_female"]:
            reasons.append("nik_gender_mismatch")
        elif "LAKI" in g_up and info["is_female"]:
            reasons.append("nik_gender_mismatch")

    return reasons
