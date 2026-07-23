"""Spatial label->value pairing using OCR line geometry.

On form documents (KIR, STNK) the value sits in a fixed place RELATIVE
to its label: same row, to the right (or the row directly below when
the layout wraps). Text-order pairing guesses; geometry knows.
This module finds each field's label BOX and reads the value from the
boxes beside it — the same idea that took STNK plate from 33% to 100%
in the trained-detector path, applied to the rule path with no model.

Items come from the main OCR pass (extract_text_from_image with
return_items=True): {text, conf, x0, x1, cy, h}.
"""
import difflib
import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

# Per-type: field -> label phrases as printed on the documents
LABELS = {
    "KIR": {
        "owner_name": ["NAMA PEMILIK"],
        "certificate_number": ["NOMOR UJI KENDARAAN", "NOMOR UJI"],
        "vehicle_id": ["NOMOR REGISTRASI KENDARAAN", "NOMOR REGISTRASI"],
        "nomor_rangka": ["NOMOR RANGKA KENDARAAN", "NOMOR RANGKA"],
        "nomor_mesin": ["NOMOR MOTOR PENGGERAK", "NOMOR MESIN"],
        "valid_until": ["MASA BERLAKU UJI BERKALA", "MASA BERLAKU UJI", "MASA BERLAKU"],
        "jbb_kg": ["JBB/JBKB", "JBB / JBKB"],
        "daya_angkut": ["DAYA ANGKUT (ORANG/KG)", "DAYA ANGKUT"],
        "kelas_jalan": ["KELAS JALAN"],
        # spec fields: the customer grades on these three
        "hasil_uji": ["HASIL UJI", "KETERANGAN", "STATUS UJI"],
        # The vehicle's dimensions are three separate labelled rows, and OCR
        # emits the label and its number as separate lines — only geometry can
        # pair them. (The single "AxBxC" string on the card is the cargo tub,
        # a DIFFERENT measurement; see spec_fields._DIM_CARGO.)
        "panjang": ["PANJANG"],
        "lebar": ["LEBAR"],
        "tinggi": ["TINGGI"],
        "kubikasi": ["ISI SILINDER", "KUBIKASI"],
    },
    "STNK": {
        "owner": ["NAMA PEMILIK"],
        "nomor_polisi": ["NOMOR REGISTRASI", "NOMOR POLISI"],
        "nomor_rangka": ["NOMOR RANGKA/NIK/VIN", "NOMOR RANGKA"],
        "nomor_mesin": ["NOMOR MESIN"],
        "tax_valid_to": ["BERLAKU SAMPAI"],
        "brand": ["MERK"],
        "year": ["TAHUN PEMBUATAN", "THN PEMBUATAN"],
        # alamat had no geometry label at all, so the text-order path's
        # "NAME OF OWNE" (the neighbouring English label) was never corrected
        "alamat": ["ALAMAT"],
        # spec fields
        "model": ["MODEL"],
        "jenis": ["JENIS"],
    },
    # A SIM prints label:value rows too; geometry was never run on it (see
    # pair_fields_spatially), so the class/expiry came from regex alone.
    "SIM": {
        "sim_number": ["NO SIM", "NOMOR SIM", "NO. SIM"],
        "nama": ["NAMA", "NAME"],
        "alamat": ["ALAMAT", "ADDRESS"],
        "expiry_date": ["BERLAKU S/D", "BERLAKU SAMPAI", "BERLAKU HINGGA", "VALID UNTIL"],
        "tanggal_lahir": ["TANGGAL LAHIR", "TGL LAHIR", "DATE OF BIRTH"],
    },
    # KTP prints label : value rows in the left column; tempat_lahir and
    # tanggal_lahir intentionally share one combined label row
    "KTP": {
        "nik": ["NIK"],
        "nama": ["NAMA"],
        "tempat_lahir": ["TEMPAT/TGL LAHIR", "TEMPAT TGL LAHIR"],
        "tanggal_lahir": ["TEMPAT/TGL LAHIR", "TEMPAT TGL LAHIR"],
        "jenis_kelamin": ["JENIS KELAMIN"],
        "kecamatan": ["KECAMATAN"],
        "kel_desa": ["KEL/DESA", "KEL DESA"],
        "agama": ["AGAMA"],
        "status_perkawinan": ["STATUS PERKAWINAN"],
        "pekerjaan": ["PEKERJAAN"],
        "kewarganegaraan": ["KEWARGANEGARAAN"],
        "berlaku_hingga": ["BERLAKU HINGGA"],
    },
}

# Value shape patterns per field (label words never match these)
PATTERNS = {
    "nomor_polisi": re.compile(r"[A-Z]{1,2}[\s-]?\d{3,4}[\s-]?[A-Z]{0,3}"),
    "vehicle_id": re.compile(r"[A-Z]{1,2}[\s-]?\d{3,4}[\s-]?[A-Z]{0,3}"),
    # >=3 real digits: English words despaced ("VEHICLE OWNERSHIP DOC")
    # must never pass as a VIN
    "nomor_rangka": re.compile(r"(?=(?:[A-Z]*\d){3})[A-Z0-9]{12,17}"),
    "nomor_mesin": re.compile(r"(?=[A-Z0-9]*\d)[A-Z0-9]{6,12}"),
    "tax_valid_to": re.compile(r"\d{1,2}[-/ ]\d{1,2}[-/ ]\d{4}|\d{1,2}\s?[A-Z]{3,9}\s?\d{4}"),
    "valid_until": re.compile(r"\d{1,2}[-/ ]\d{1,2}[-/ ]\d{4}|\d{1,2}\s?[A-Z]{3,9}\s?\d{4}"),
    "certificate_number": re.compile(r"[A-Z]{2,3}\d{4,8}[A-Z]?|(?=[A-Z]*\d)[A-Z0-9]{6,14}"),
    "jbb_kg": re.compile(r"[\d.,]+\s*KG|\d[\d.,]{2,}"),
    "year": re.compile(r"(19|20)\d{2}"),
    "kelas_jalan": re.compile(r"\b(I{1,3}|IV|V)\b"),
    "nik": re.compile(r"\d{16}"),
    "tanggal_lahir": re.compile(r"\d{1,2}[-/ ]\d{1,2}[-/ ](19|20)\d{2}"),
    "berlaku_hingga": re.compile(r"\d{1,2}[-/ ]\d{1,2}[-/ ](19|20)\d{2}"),
    # spec fields
    "hasil_uji": re.compile(r"TIDAK\s*LULUS|LULUS|MEMENUHI|LAIK\s*JALAN|GAGAL"),
    # each axis is a bare millimetre figure ("6000", "2,050")
    "panjang": re.compile(r"\d[\d.,]{2,6}"),
    "lebar": re.compile(r"\d[\d.,]{2,6}"),
    "tinggi": re.compile(r"\d[\d.,]{2,6}"),
    "kubikasi": re.compile(r"[\d.,]{3,7}\s*(?:CC|CM3)?"),
    # the card prints "MOBIL BARANG/BEBAN"; stopping at "BARANG" reports a
    # truncation of the printed value (and this vocabulary is a SECOND copy of
    # the one in spec_fields — fixing only that one left this path truncating)
    "jenis": re.compile(r"MOBIL\s*BARANG(?:\s*/\s*BEBAN)?|MOBIL\s*PENUMPANG|MOBIL\s*BUS|SEPEDA\s*MOTOR|KENDARAAN\s*KHUSUS"),
    "sim_number": re.compile(r"[\d\-\s]{10,20}"),
    "expiry_date": re.compile(r"\d{1,2}[-/ ]\d{1,2}[-/ ](19|20)\d{2}"),
}

# Fields whose value is a single alphanumeric token; OCR sprinkles
# dots/spaces/colons into them, and the row often glues label residue
_TOKEN_FIELDS = ("nomor_rangka", "nomor_mesin", "certificate_number", "nik")

# Validity dates: any document in circulation carries a year in this
# window — "30-12-1899" (spreadsheet epoch) or a birth year is a misread
_DATE_FIELDS = ("valid_until", "tax_valid_to")
_YEAR_WINDOW = (2015, 2040)


def _plausible_date(text: str) -> bool:
    m = re.search(r"(19|20)\d{2}", text or "")
    return bool(m) and _YEAR_WINDOW[0] <= int(m.group(0)) <= _YEAR_WINDOW[1]


# Free-text name fields: no shape pattern, but garbage is detectable
_NAME_FIELDS = ("owner", "owner_name", "nama", "tempat_lahir")

# Completion upgrade applies only where a legit value can be multi-word
# ("BELUM KAWIN"); single-word vocabularies (agama) can only be harmed —
# the row sweep may glue the neighbouring column on ("ISLAM KAWIN")
_COMPLETABLE_FIELDS = _NAME_FIELDS + ("status_perkawinan",)
_NAME_STOPWORDS = re.compile(
    r"\b(NAMA|PEMILIK|OWNER|NAME|ALAMAT|ADDRESS|COMPANY|REGISTRATION|"
    r"NUMBER|NOMOR|VEHICLE|IDENTIFICATION|LAHIR|GOL|DARAH|"
    # values of OTHER closed-vocabulary fields leaking into a name slot
    r"LAKI|PEREMPUAN|PRIA|WANITA|ISLAM|KRISTEN|KATOLIK|HINDU|BUDDHA|KHONGHUCU|"
    r"KAWIN|CERAI|SEUMUR|BI|BII|UMUM)\b")


def _is_gazetteer_place(value: str) -> bool:
    """Long compound place names leaking into a name slot are detectable:
    exact despaced hit in the kecamatan gazetteer (>=8 chars — short
    entries collide with real person names)."""
    v = re.sub(r"[^A-Z]", "", (value or "").upper())
    if len(v) < 8:
        return False
    try:
        from app.utils.id_reference import kecamatan_names
        return any(re.sub(r"[^A-Z]", "", k) == v for k in kecamatan_names())
    except Exception:
        return False

# ISO 3779: VINs never contain I, O or Q — OCR confusions are decodable
_VIN_FIX = str.maketrans({"I": "1", "O": "0", "Q": "0"})


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def _label_score(item_text: str, label: str) -> float:
    """How label-like is this OCR line? Glued and garbled tolerated.
    The label's last word is the discriminating one on NOMOR-X forms
    (MESIN vs POLISI vs RANGKA) — finding it verbatim earns a bonus so
    garbled-but-right labels outrank wrong-but-similar ones."""
    a, b = _norm(item_text), _norm(label)
    if not a or not b:
        return 0.0
    if len(b) <= 4:
        # short labels (NIK, MERK, NAMA): containment/fuzzy would match
        # inside words like ELEKTRONIK — exact or prefix only
        return 1.0 if a == b or a.startswith(b) else 0.0
    if b in a:
        return 1.0
    score = difflib.SequenceMatcher(None, a, b).ratio()
    words = re.findall(r"[A-Z]{4,}", (label or "").upper())
    if words and words[-1] in a:
        score = min(1.0, score + 0.15)
    return score


def _value_right_of(items: List[Dict], label_item: Dict) -> str:
    """Concatenate boxes on the label's row, right of the label.
    Stops at the first large horizontal gap — that is the column
    boundary on two-column layouts (STNK), not part of the value."""
    h = max(label_item["h"], 12.0)
    row_tol = h * 0.7
    right = [it for it in items
             if it is not label_item and it["text"].strip()
             and abs(it["cy"] - label_item["cy"]) <= row_tol
             and it["x0"] >= label_item["x1"] - h]
    right.sort(key=lambda it: it["x0"])
    picked: List[Dict] = []
    prev_x1 = None
    for it in right:
        gap = it["x0"] - (label_item["x1"] if prev_x1 is None else prev_x1)
        # First box may sit far right when OCR truncated the label ("MODEL"->
        # "ODEL" shrinks its box, widening the gap to the value). Allow a
        # generous FIRST reach; the tight SECOND-box rule (2.5*h from the value
        # already found) is what actually fends off the far watermark column.
        if gap > (12 * h if prev_x1 is None else 2.5 * h):
            break
        picked.append(it)
        prev_x1 = it["x1"] if prev_x1 is None else max(prev_x1, it["x1"])
    return " ".join(it["text"].strip() for it in picked).strip()


def _value_below(items: List[Dict], label_item: Dict) -> str:
    """First box on the next row overlapping the label horizontally."""
    below = [it for it in items
             if it is not label_item and it["text"].strip()
             and 0 < it["cy"] - label_item["cy"] <= max(label_item["h"], 12.0) * 2.2
             and it["x0"] < label_item["x1"] + 40]
    below.sort(key=lambda it: (it["cy"], it["x0"]))
    return below[0]["text"].strip() if below else ""


def _row_below_text(items: List[Dict], label_item: Dict) -> str:
    """The whole row under the label, joined left-to-right — labels wrap
    on dense forms and the value follows the wrapped half."""
    h = max(label_item["h"], 12.0)
    below = [it for it in items
             if it is not label_item and it["text"].strip()
             and 0 < it["cy"] - label_item["cy"] <= h * 2.2]
    below.sort(key=lambda it: it["x0"])
    return " ".join(it["text"].strip() for it in below).strip()


def _plausible_name(value: str) -> bool:
    v = (value or "").upper().strip()
    return (len(v) >= 3 and not re.search(r"\d", v)
            and re.fullmatch(r"[A-Z .,'()\-]+", v) is not None
            and not _NAME_STOPWORDS.search(v))


def _canonical(field: str, value: str) -> str:
    """Field-specific canonical form for the API output."""
    if field == "jbb_kg":
        digits = re.sub(r"[^0-9]", "", value or "")
        return digits or ""
    if field == "nomor_rangka" and len(value or "") == 17:
        return value.translate(_VIN_FIX)
    return value or ""


def _extract_value(field: str, raw: str) -> str:
    """Reduce row text to the value: strip a leading colon/label residue,
    apply the field's shape pattern when one exists."""
    text = re.sub(r"^[\s:.\-]+", "", raw or "").strip()
    # e-KTPs since 2016 print a lifetime validity instead of a date; by
    # law even dated cards remain valid — never treat this as expiry
    if field == "berlaku_hingga" and "SEUMURHIDUP" in re.sub(r"[^A-Z]", "", text.upper()):
        return "SEUMUR HIDUP"
    pattern = PATTERNS.get(field)
    if pattern:
        if field in _TOKEN_FIELDS:
            # glued label residue ends at the last colon; separators
            # inside the token are OCR noise
            if ":" in text:
                text = text.rsplit(":", 1)[1]
            hay = re.sub(r"[^A-Z0-9]", "", text.upper())
        else:
            hay = text.upper()
        if field in _DATE_FIELDS:
            from app.utils.validators import normalize_expiry_date
            for m in pattern.finditer(hay):
                if _plausible_date(m.group(0)):
                    raw_date = m.group(0).strip()
                    return normalize_expiry_date(raw_date) or raw_date
            return ""
        if field == "kelas_jalan":
            # 'III' contains 'I': the LONGEST roman numeral on the row wins
            matches = [m.group(0) for m in pattern.finditer(hay)]
            return max(matches, key=len) if matches else ""
        m = pattern.search(hay)
        return _canonical(field, m.group(0).strip()) if m else ""
    # free-text fields: cut at a next-label boundary if present
    if field == "tempat_lahir":
        # combined "JAKARTA, 17-08-1990" row: place ends at comma/digit
        text = re.split(r"[,\d]", text)[0]
    text = re.split(
        r"\b(ALAMAT|OWNER|ADDRESS|VEHICLE|IDENTIFICATION|GOL|DARAH|AGAMA|"
        r"PEKERJAAN|KEWARGANEGARAAN|KECAMATAN|BERLAKU)\b", text,
        flags=re.IGNORECASE)[0]
    text = text.strip(" :.-")
    if field in _NAME_FIELDS and not _plausible_name(text):
        return ""
    return text


# These documents print their labels bilingually ("NAMA PEMILIK / NAME OF
# OWNER"), and the text-order path routinely returns the label's own tail as
# the value: alamat="NAME OF OWNE", vin_chassis="NIK/VIN", tipe="JENIS". A
# value that IS a printed label is never that label's value, whatever field it
# landed in — so reject it once, here, instead of per-field forever.
_PRINTED_LABELS = [
    # Indonesian
    "NAMA PEMILIK", "ALAMAT", "MERK", "TIPE", "JENIS", "MODEL", "WARNA",
    "TAHUN PEMBUATAN", "ISI SILINDER", "NOMOR RANGKA", "NOMOR MESIN",
    "NOMOR POLISI", "NOMOR REGISTRASI", "BAHAN BAKAR", "BERLAKU SAMPAI",
    "MASA BERLAKU", "NOMOR URUT", "KODE WILAYAH", "NIK", "NIK/VIN",
    "TEMPAT TANGGAL LAHIR", "JENIS KELAMIN", "GOLONGAN DARAH", "KEWARGANEGARAAN",
    "NOMOR UJI", "DAYA ANGKUT", "KELAS JALAN", "HASIL UJI",
    # English subtitles printed alongside them
    "NAME OF OWNER", "ADDRESS", "BRAND", "TYPE", "YEAR OF MAKE", "COLOUR",
    "COLOR", "CHASSIS NUMBER", "ENGINE NUMBER", "REGISTRATION NUMBER",
    "CYLINDER CAPACITY", "VALID UNTIL", "FUEL TYPE", "OWNER",
]
_LABEL_FORMS = {re.sub(r"[^A-Z]", "", lab.upper()) for lab in _PRINTED_LABELS}


def _is_label_residue(value: str) -> bool:
    """True when the value is (a truncation of) a label printed on the card."""
    d = re.sub(r"[^A-Z]", "", str(value or "").upper())
    if len(d) < 3:
        return False
    if d in _LABEL_FORMS:
        return True
    # OCR clips labels mid-word ("NAME OF OWNE"); require a solid prefix so a
    # real value can't be swallowed by a short label.
    return any(len(d) >= 6 and (lab.startswith(d) or d.startswith(lab))
               for lab in _LABEL_FORMS)


def _existing_is_valid(field: str, value) -> bool:
    """Merge policy input: does the current value already look right?"""
    s = str(value or "")
    if not s:
        return False
    if _is_label_residue(s):
        return False
    if field == "tempat_lahir":
        # birth places are a closed vocabulary (kabupaten+kecamatan);
        # garbage like "EEZSO OEO OOOE" passes letter-shape checks but
        # never gazetteer confirmation
        if not _plausible_name(s):
            return False
        try:
            import difflib
            from app.utils.id_reference import kabupaten_names, kecamatan_names
            v = re.sub(r"\s+", " ", s.upper().strip())
            gaz = kabupaten_names() + kecamatan_names()
            if not gaz:
                return True
            first = v.split(" ")[0]
            return bool(difflib.get_close_matches(v, gaz, n=1, cutoff=0.8)
                        or (len(first) >= 4 and first in gaz))
        except Exception:
            return True
    if field in _NAME_FIELDS:
        return _plausible_name(s)
    if field in _DATE_FIELDS:
        return _plausible_date(s.upper())
    pattern = PATTERNS.get(field)
    if pattern is None:
        return True
    if field in _TOKEN_FIELDS:
        # single-token fields must be the token alone, not label+token
        return pattern.fullmatch(re.sub(r"[^A-Z0-9]", "", s.upper())) is not None
    return pattern.search(s.upper()) is not None


def _evict_vin_duplicates(fields: Dict) -> None:
    """Certificate/engine values equal to the VIN are leaks, not values."""
    rangka = fields.get("nomor_rangka")
    rangka_tok = re.sub(r"[^A-Z0-9]", "", str(
        (rangka.get("value") if isinstance(rangka, dict) else rangka) or "").upper())
    if not rangka_tok:
        return
    for field in ("certificate_number", "nomor_mesin"):
        rec = fields.get(field)
        val = rec.get("value") if isinstance(rec, dict) else rec
        if val and re.sub(r"[^A-Z0-9]", "", str(val).upper()) == rangka_tok:
            fields.pop(field, None)


def _complete_short_mesin(items: List[Dict], fields: Dict) -> None:
    """A truncated engine read is often completed verbatim elsewhere on the
    page (STNK repeats it in the tax block): a longer token that STARTS
    WITH the current read and still fits the shape is the fuller read."""
    rec = fields.get("nomor_mesin")
    val = str((rec.get("value") if isinstance(rec, dict) else rec) or "")
    tok = re.sub(r"[^A-Z0-9]", "", val.upper())
    if not (6 <= len(tok) < 12):
        return
    pattern = PATTERNS["nomor_mesin"]
    best = tok
    for it in items:
        hay = re.sub(r"[^A-Z0-9]", "", it["text"].upper())
        idx = hay.find(tok)
        while idx >= 0:
            for ln in range(12, len(tok), -1):
                cand = hay[idx:idx + ln]
                if len(cand) > len(best) and pattern.fullmatch(cand):
                    best = cand
                    break
            idx = hay.find(tok, idx + 1)
    if best != tok:
        if isinstance(rec, dict):
            rec["value"] = best
            prov = rec.setdefault("provenance", {})
            if isinstance(prov, dict):
                prov["completed_from_page"] = True
        else:
            fields["nomor_mesin"] = best


# Main-dimension plausibility (mm), per position. Rejects the length misread
# as "0009", stray weights, and — because each position has its own range —
# the cargo-tub decoy whose numbers land in the wrong slots.
_DIM_RANGE = {"panjang": (3000, 14000), "lebar": (1400, 2700), "tinggi": (1400, 4300)}


def _assemble_kir_dimensi(items: List[Dict], fields: Dict) -> None:
    """Build `dimensi` = "P X L X T mm" from the three stacked numbers under
    the "DIMENSI UTAMA" label.

    The main dimension is printed as three separate label rows whose OCR is
    unreliable (length "6000" reads "0009"; the "Panjang/Lebar" labels garble),
    and the card ALSO prints a same-shaped cargo-tub figure. So: take the
    numbers in the value COLUMN below the main-dimension label, and accept a
    triple ONLY when all three land in their own plausible range. A misread or
    the cargo tub fails a range and the whole field stays needs_review — never
    a wrong truck dimension.
    """
    rec = fields.get("dimensi")
    if (rec.get("value") if isinstance(rec, dict) else rec):
        return
    # Prefer the "DIMENSI UTAMA" label as a top boundary; the recoverable card
    # often loses that label to OCR, so fall back to scanning all rows. The
    # strict per-position ranges below are what keep the scan safe, and the
    # cargo-tub "(AxBxC)" is one token (not three stacked), so it never forms
    # a column here.
    label_cy = -1e9
    for it in items:
        n = _norm(it["text"])
        if "DIMENSIUTAMA" in n or ("DIMENSI" in n and "BAKMUATAN" not in n and "TANGKI" not in n):
            label_cy = it["cy"]
            break
    nums = []
    for it in items:
        if it["cy"] <= label_cy:
            continue
        m = re.fullmatch(r"[:\s]*([\d.,]{3,7})\s*", it["text"])
        if not m:
            continue
        digits = re.sub(r"[^0-9]", "", m.group(1))
        if digits:
            nums.append((it["cy"], it["x0"], int(digits)))
    if len(nums) < 3:
        return
    # the three values share a vertical column; group by x, top-to-bottom
    nums.sort(key=lambda t: (t[1], t[0]))
    best = None
    for i in range(len(nums)):
        col = sorted([t for t in nums if abs(t[1] - nums[i][1]) <= 60], key=lambda t: t[0])
        if len(col) >= 3:
            p, l, tg = col[0][2], col[1][2], col[2][2]
            if (_DIM_RANGE["panjang"][0] <= p <= _DIM_RANGE["panjang"][1]
                    and _DIM_RANGE["lebar"][0] <= l <= _DIM_RANGE["lebar"][1]
                    and _DIM_RANGE["tinggi"][0] <= tg <= _DIM_RANGE["tinggi"][1]):
                best = (p, l, tg)
                break
    if best:
        fields["dimensi"] = {"value": f"{best[0]} X {best[1]} X {best[2]} mm",
                             "confidence": 0.6,
                             "provenance": {"method": "dimensi_column"}}


def _ktp_kecamatan_from_gazetteer(items: List[Dict], fields: Dict) -> None:
    """When the Kecamatan label row was unreadable, a UNIQUE exact
    gazetteer hit among the OCR boxes is strong evidence — 6,907 known
    kecamatan names, exact despaced match, ambiguity skips."""
    rec = fields.get("kecamatan")
    if (rec.get("value") if isinstance(rec, dict) else rec):
        return
    try:
        from app.utils.id_reference import kecamatan_names
        gaz = {re.sub(r"[^A-Z]", "", k): k for k in kecamatan_names()}
    except Exception:
        return
    hits = set()
    for it in items:
        v = re.sub(r"[^A-Z]", "", it["text"].upper())
        if len(v) >= 6 and v in gaz:
            hits.add(gaz[v])
    if len(hits) == 1:
        fields["kecamatan"] = {"value": hits.pop(), "confidence": 0.65,
                               "provenance": {"method": "gazetteer_unique"}}


def _ktp_nama_from_nik_anchor(items: List[Dict], fields: Dict) -> None:
    """On every KTP the name row is printed immediately below the NIK row.
    When the 'Nama' label box was not read, anchor on the NIK box and take
    the colon-led box just under it. Replaces an existing value only when
    that value is a single word and the anchored read is a fuller name."""
    existing = fields.get("nama")
    ev = str((existing.get("value") if isinstance(existing, dict) else existing) or "").strip()
    ev_bad = bool(ev) and (not _plausible_name(ev) or _is_gazetteer_place(ev))
    if ev and " " in ev and not ev_bad:
        return
    nik_box = None
    for it in items:
        digits = re.sub(r"[^0-9]", "", it["text"])
        if len(digits) >= 16 or _norm(it["text"]).startswith("NIK"):
            nik_box = it
            break
    if nik_box is None:
        return
    h = max(nik_box["h"], 12.0)
    cands = [it for it in items
             if it is not nik_box and it["text"].strip()
             and 0 < it["cy"] - nik_box["cy"] <= 2.5 * h
             and (it["text"].strip().startswith(":")
                  or _norm(it["text"]).startswith("NAMA"))]
    cands.sort(key=lambda it: it["cy"])
    for cand in cands:
        text = re.sub(r"^\s*NAMA\s*[:.]?\s*", "", cand["text"], flags=re.IGNORECASE)
        value = _extract_value("nama", text)
        if not value:
            continue
        if not ev or ev_bad or (" " not in ev and " " in value):
            fields["nama"] = {"value": value, "confidence": 0.7,
                              "provenance": {"method": "nik_anchor"}}
        return


_SIM_CLASSES = {"A", "BI", "BII", "C", "D", "A UMUM", "BI UMUM", "BII UMUM"}


def _sim_class_from_items(items: List[Dict], fields: Dict) -> None:
    """New-format SIMs print the class as a standalone unlabeled box in
    the card's top area. Accept it only when the reading is EXACTLY a
    canonical class and unambiguous (one distinct class on the card)."""
    rec = fields.get("class")
    if (rec.get("value") if isinstance(rec, dict) else rec):
        return
    max_cy = max((it["cy"] for it in items), default=0.0)
    seen = set()
    for it in items:
        text = re.sub(r"\s+", " ", it["text"].strip().upper())
        if text in _SIM_CLASSES and it["cy"] <= 0.5 * max_cy:
            seen.add(text)
    if len(seen) == 1:
        fields["class"] = {"value": seen.pop(), "confidence": 0.7,
                           "provenance": {"method": "standalone_class_box"}}


def _sim_name_from_layout(items: List[Dict], fields: Dict) -> None:
    """Old-format SIMs enumerate rows: '1. NAME' / '2. BIRTHPLACE, DOB'.
    The name is the '1.'-row's text, or the box directly above the '2.'
    row when the name row lost its number. A 'name' containing digits is
    the birth row misfiled — treated as missing."""
    rec = fields.get("name") or fields.get("nama")
    ev_raw = str((rec.get("value") if isinstance(rec, dict) else rec) or "").strip()
    # extractor sometimes keeps label residue (":PUDIN") — judge and keep
    # the CLEANED value, not the residue
    ev = re.sub(r"^[\s:.\-]+", "", ev_raw)
    if ev and not re.search(r"\d", ev) and _plausible_name(ev):
        if ev != ev_raw:
            if isinstance(rec, dict):
                rec["value"] = ev
            else:
                fields["name"] = ev
        return
    value = ""
    for it in items:
        m = re.match(r"^\s*1[.,]\s*(.+)$", it["text"])
        if m:
            cand = _extract_value("nama", m.group(1))
            if cand and not re.search(r"\d", cand):
                value = cand
                break
    if not value:
        row2 = next((it for it in items if re.match(r"^\s*2[.,]\s*", it["text"])), None)
        if row2 is not None:
            h = max(row2["h"], 12.0)
            above = [it for it in items
                     if it is not row2 and it["text"].strip()
                     and 0 < row2["cy"] - it["cy"] <= 2.2 * h
                     and it["x0"] < row2["x1"]]
            above.sort(key=lambda it: -it["cy"])
            for cand_box in above:
                cand = _extract_value("nama", cand_box["text"])
                if cand and not re.search(r"\d", cand):
                    value = cand
                    break
    if value:
        fields["name"] = {"value": value, "confidence": 0.7,
                          "provenance": {"method": "sim_layout_anchor"}}
    elif ev and (re.search(r"\d", ev) or not _plausible_name(ev)):
        # birth row / gender word ("PRIA" beside a redacted name) is not
        # a name — empty routes to review, wrong does not
        fields.pop("name", None)


def pair_fields_spatially(doc_type: str, items: List[Dict], fields: Dict) -> Dict:
    """Fill missing / replace implausible fields using geometry.

    Same merge policy as the trained-detector path: never overwrite a
    value that already matches its field's shape.
    """
    if (doc_type or "").upper() == "SIM" and items:
        # SIM-specific layout anchors run first (the class box is a standalone
        # glyph with no label to pair against), then fall through to the label
        # loop below — which SIM used to skip entirely, leaving its number,
        # expiry and address to the regex path alone.
        _sim_class_from_items(items, fields)
        _sim_name_from_layout(items, fields)
    labels = LABELS.get((doc_type or "").upper())
    if not labels or not items:
        return fields

    # Rule-path rescue: an invalid token value often glues label residue
    # to the RIGHT token ("NIKVIN : MHY...") — recover it before asking
    # geometry, which can land on a nearby watermark instead
    for field in _TOKEN_FIELDS:
        if field not in labels:
            continue
        rec = fields.get(field)
        val = rec.get("value") if isinstance(rec, dict) else rec
        if val and not _existing_is_valid(field, val):
            rescued = _extract_value(field, str(val))
            if rescued:
                if isinstance(rec, dict):
                    rec["value"] = rescued
                else:
                    fields[field] = rescued

    # The rangka leaking into certificate/engine slots is a rule-path
    # failure mode; a duplicate of the VIN is never those fields' value
    _evict_vin_duplicates(fields)

    # Each label box serves only the field it resembles MOST — "NOMOR UJI"
    # must not moonlight as "NOMOR MESIN" when the real mesin label is faint
    item_scores = [
        {f: max(_label_score(it["text"], ph) for ph in phs) for f, phs in labels.items()}
        for it in items
    ]
    for field in labels:
        # Plausible label boxes, best first; only near-ties are tried as
        # fallbacks — a distant runner-up is usually a DIFFERENT label
        cands = []
        for it, per_field in zip(items, item_scores):
            s = per_field[field]
            if s >= 0.62 and s >= max(per_field.values()) - 0.02:
                cands.append((s, it))
        cands.sort(key=lambda c: -c[0])
        cands = [c for c in cands if c[0] >= cands[0][0] - 0.08][:3] if cands else []
        value, best_score = "", 0.0
        for s, cand in cands:
            # OCR often glues "LABEL : VALUE" into one box — the value
            # is then INSIDE the label box, after the colon
            v = ""
            if ":" in cand["text"]:
                tail = cand["text"].split(":", 1)[1].strip()
                if len(tail) >= 3:
                    v = _extract_value(field, tail)
            if not v:
                v = _extract_value(field, _value_right_of(items, cand))
            if not v:
                v = _extract_value(field, _value_below(items, cand))
            if not v and PATTERNS.get(field) is not None:
                v = _extract_value(field, _row_below_text(items, cand))
            if v:
                value, best_score = v, s
                break
        if not value:
            continue
        rec = {"value": value, "confidence": round(0.55 + 0.3 * best_score, 3),
               "provenance": {"method": "spatial_pairing", "label_score": round(best_score, 2)}}
        existing = fields.get(field)
        existing_val = existing.get("value") if isinstance(existing, dict) else existing
        if not existing_val or not _existing_is_valid(field, existing_val):
            fields[field] = rec
            continue
        # completion upgrade: the rule value is a word-subset of what the
        # label row actually prints ("KAWIN" from "BELUM KAWIN") — the
        # fuller row read wins; it only adds words physically beside it
        ex = str(existing_val).upper().strip()
        if (field in _COMPLETABLE_FIELDS and len(value) > len(ex)
                and re.search(rf"\b{re.escape(ex)}\b", value.upper())):
            fields[field] = rec
            continue
        # Cards print several dates and several weights; the value
        # beside ITS OWN label is the truth — trust geometry over
        # sequence heuristics. Diagnosed leaks: KIR rule path took
        # "JBB<=3500kg" regulation text as JBB; KTP rule path took the
        # ISSUE date under the photo as berlaku_hingga
        if field in ("valid_until", "jbb_kg", "berlaku_hingga") and best_score >= 0.85:
            from app.utils.validators import normalize_expiry_date
            new_c = normalize_expiry_date(value) or _canonical(field, value) or value
            old_c = (normalize_expiry_date(str(existing_val))
                     or _canonical(field, str(existing_val)) or str(existing_val))
            if new_c != old_c:
                fields[field] = rec

    # KTP layout invariant: the name row sits immediately below the NIK
    # row — rescue nama when the "Nama" label box itself was not read
    if (doc_type or "").upper() == "KTP":
        _ktp_nama_from_nik_anchor(items, fields)
        _ktp_kecamatan_from_gazetteer(items, fields)

    if (doc_type or "").upper() == "KIR":
        _assemble_kir_dimensi(items, fields)

    # the fill loop itself can re-leak the VIN into cert/mesin (their
    # label rows sometimes CONTAIN the rangka on dense paper forms)
    _evict_vin_duplicates(fields)
    _complete_short_mesin(items, fields)

    # Canonicalize whatever source produced these (rule path included)
    for field in ("jbb_kg", "nomor_rangka"):
        rec = fields.get(field)
        val = rec.get("value") if isinstance(rec, dict) else rec
        if val:
            canon = _canonical(field, str(val))
            if canon and canon != val:
                if isinstance(rec, dict):
                    rec["value"] = canon
                else:
                    fields[field] = canon

    # A plate reading that is a prefix of the VIN is the VIN, misread as
    # a plate — drop it; missing routes to needs_review, wrong does not
    rangka = fields.get("nomor_rangka")
    rangka_val = re.sub(r"[^A-Z0-9]", "", str(
        (rangka.get("value") if isinstance(rangka, dict) else rangka) or "").upper())
    for plate_field in ("vehicle_id", "nomor_polisi"):
        rec = fields.get(plate_field)
        if not isinstance(rec, dict) or (rec.get("provenance") or {}).get("method") != "spatial_pairing":
            continue
        plate = re.sub(r"[^A-Z0-9]", "", str(rec.get("value") or "").upper())
        if plate and rangka_val and plate in rangka_val:
            fields.pop(plate_field, None)
    return fields
