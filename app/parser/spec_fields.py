"""Fields the customer KYC spec requires that no extractor produced.

Three groups:

  title            — every type. Printed as a header; OCR mangles it, so we
                     fuzzy-match against the known header of each type and
                     fall back to the classifier's verdict.
  KIR              — hasil_uji (pass/fail), dimensi, kubikasi. Nothing in the
                     codebase emitted these; the customer grades on all three.
  STNK             — jenis_registrasi.

Plus derive_aliases(), the single writer of the English alias keys. Extractors
used to write English+Indonesian twins up front, and later stages (spatial
pairing, the YOLO detector) only ever repaired the Indonesian one — so the
English twin kept whatever the weak text-order path first guessed, which was
routinely a chunk of the printed label ("vin_chassis": "NIK/VIN"). Deriving the
aliases once, at the end, from the canonical field makes that class of bug
unrepresentable.
"""
import contextvars
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------- journal
#
# Every value this module DROPS is the system choosing needs_review over a
# guess — the single most important thing it does, and until now it existed
# only as a log line nobody reads. Record each drop for the caller, so the
# console can show "we read this, and refused to ship it, because …".
#
# Request-scoped rather than global: two concurrent uploads must not pour their
# drops into one another's report.
_JOURNAL: contextvars.ContextVar = contextvars.ContextVar("field_journal", default=None)


def journal_begin() -> None:
    _JOURNAL.set([])


def journal_entries() -> List[Dict[str, Any]]:
    return list(_JOURNAL.get() or [])


def _record_drop(field: str, value: Any, reason: str) -> None:
    j = _JOURNAL.get()
    if j is not None:
        j.append({"field": field, "value": str(value), "reason": reason,
                  "outcome": "needs_review"})


def _drop(fields: Dict[str, Any], key: str, value: Any, reason: str) -> None:
    """Remove a field and say why. A dropped field becomes needs_review."""
    logger.info("dropping %s = %r (%s)", key, value, reason)
    _record_drop(key, value, reason)
    fields.pop(key, None)

# Canonical -> alias keys, PER DOCUMENT TYPE. Scoping matters: `nomor_polisi`
# is canonical on an STNK but an alias of `vehicle_id` on a KIR, and a
# type-blind rule would let the KIR entry delete the STNK's plate.
ALIASES = {
    "STNK": {
        "nomor_polisi": ["plate_number"],
        "nomor_rangka": ["vin_chassis", "chassis_number"],
        "nomor_mesin": ["engine_number"],
        "owner": ["owner_name"],
        "alamat": ["address"],
        "tax_valid_to": ["masa_berlaku", "valid_until"],
    },
    "KIR": {
        # the spec's "plate / registration number" is what the card labels
        # NOMOR REGISTRASI KENDARAAN, which this codebase calls vehicle_id
        "vehicle_id": ["nomor_polisi", "plate_number"],
        "nomor_rangka": ["vin_chassis", "chassis_number"],
        "nomor_mesin": ["engine_number"],
        "valid_until": ["masa_berlaku"],
        "owner_name": ["owner"],
    },
    "SIM": {
        # the spec calls it "Type of DL"; the SIM extractor calls it `class`
        "class": ["tipe_sim"],
        "sim_number": ["id_number"],
        "expiry_date": ["valid_to", "masa_berlaku"],
        "name": ["nama"],
        "address": ["alamat"],
    },
    "KTP": {
        "nama": ["name"],
        "alamat": ["address"],
        "nik": ["id_number"],
    },
}

# The title as printed, per type, with the OCR-plausible variants we accept.
TITLES = {
    "STNK": {
        "canonical": "SURAT TANDA NOMOR KENDARAAN BERMOTOR",
        "variants": ["SURAT TANDA NOMOR KENDARAAN BERMOTOR",
                     "SURAT TANDA NOMOR KENDARAAN",
                     "TANDA NOMOR KENDARAAN BERMOTOR"],
    },
    "SIM": {
        "canonical": "SURAT IZIN MENGEMUDI",
        "variants": ["SURAT IZIN MENGEMUDI", "DRIVING LICENSE", "SURAT IJIN MENGEMUDI"],
    },
    "KIR": {
        "canonical": "KARTU UJI BERKALA KENDARAAN BERMOTOR",
        "variants": ["KARTU UJI BERKALA KENDARAAN BERMOTOR",
                     "BUKU UJI BERKALA KENDARAAN BERMOTOR",
                     "SURAT KETERANGAN UJI BERKALA",
                     "PENGUJIAN KENDARAAN BERMOTOR",
                     "KARTU UJI BERKALA", "BUKU UJI", "KARTU UJI"],
    },
    "KTP": {
        "canonical": "KARTU TANDA PENDUDUK",
        "variants": ["KARTU TANDA PENDUDUK", "NOMOR INDUK KEPENDUDUKAN"],
    },
}

_TITLE_MIN_RATIO = 0.72


def _despace(s: str) -> str:
    # Paddle glues and splits words unpredictably; compare on letters only.
    return re.sub(r"[^A-Z]", "", (s or "").upper())


def _set(fields: Dict[str, Any], key: str, value: Any, conf: float, method: str,
         overwrite: bool = False) -> None:
    if value in (None, "", []):
        return
    cur = fields.get(key)
    cur_val = cur.get("value") if isinstance(cur, dict) else cur
    if cur_val and not overwrite:
        return
    fields[key] = {"value": value, "confidence": round(conf, 2),
                   "provenance": {"method": method}}


# ---------------------------------------------------------------- title

def extract_title(doc_type: str, lines: List[str], fields: Dict[str, Any],
                  detection_confidence: float = 0.0) -> Dict[str, Any]:
    """Emit `title`. Prefer a title actually read off the document; fall back
    to the classifier, flagged as such in provenance so a caller can tell the
    difference between 'the card says this' and 'we inferred this'."""
    spec = TITLES.get((doc_type or "").upper())
    if not spec:
        return fields

    best_ratio, best_line = 0.0, None
    for ln in lines or []:
        hay = _despace(ln)
        if len(hay) < 6:
            continue
        for variant in spec["variants"]:
            needle = _despace(variant)
            if needle and needle in hay:
                best_ratio, best_line = 1.0, ln
                break
            r = SequenceMatcher(None, needle, hay).ratio()
            if r > best_ratio:
                best_ratio, best_line = r, ln
        if best_ratio >= 1.0:
            break

    if best_ratio >= _TITLE_MIN_RATIO:
        _set(fields, "title", spec["canonical"], min(0.99, best_ratio),
             "title_ocr_match")
        _set(fields, "title_raw", (best_line or "").strip(), best_ratio, "title_ocr_match")
    elif detection_confidence > 0:
        # The header did not survive OCR, but the body proved the type.
        _set(fields, "title", spec["canonical"], min(0.75, detection_confidence),
             "title_from_classification")
    return fields


# ------------------------------------------------------------------ KIR

# "TIDAK LULUS" contains "LULUS" — negation must be tested first, and a bare
# "LULUS" only counts as a pass when no negation appears anywhere near it.
_FAIL_PAT = re.compile(
    r"TIDAK\s*LULUS|TIDAK\s*MEMENUHI|TIDAK\s*LAIK|GAGAL|DITOLAK", re.I)
_PASS_PAT = re.compile(
    r"LULUS\s*UJI|LULUS|MEMENUHI\s*PERSYARATAN|LAIK\s*JALAN|MEMENUHI", re.I)

# DIMENSIONS — the trap on a real KIR card.
#
# The card prints the vehicle's own dimensions ("Dimensi utama kendaraan
# bermotor") as THREE SEPARATE LABELLED ROWS: Panjang / Lebar / Tinggi. It also
# prints a DIFFERENT measurement — "Dimensi bak muatan / tangki", the cargo tub
# — and THAT one is printed as a single "(4350 x 2050 x 2000) mm" string.
#
# So the only AxBxC-shaped string on the page is the WRONG answer. Grabbing it
# yields a confident, plausible, incorrect vehicle size. Assemble the real value
# from its three rows, and if all three aren't legible, emit nothing: an empty
# dimensi becomes needs_review, a cargo-tub dimensi becomes a silent error.
_DIM_CARGO = re.compile(
    r"(?:BAK\s*MUATAN|TANGKI|BAK/TANGKI)[^0-9]{0,20}"
    r"\(?\s*(\d[\d.,]{2,6})\s*[X×*]\s*(\d[\d.,]{2,6})\s*[X×*]\s*(\d[\d.,]{2,6})", re.I)
_DIM_TRIPLE = re.compile(
    r"(\d[\d.,]{2,6})\s*[X×*]\s*(\d[\d.,]{2,6})\s*[X×*]\s*(\d[\d.,]{2,6})", re.I)
# One labelled row: "Panjang : 6000 mm" (OCR mangles the label: "Panjange")
_DIM_ROW = {
    "panjang": re.compile(r"\bPANJANG\w{0,2}\b\D{0,8}(\d[\d.,]{2,6})", re.I),
    "lebar":   re.compile(r"\bLEBAR\w{0,2}\b\D{0,8}(\d[\d.,]{2,6})", re.I),
    "tinggi":  re.compile(r"\bTINGGI\w{0,2}\b\D{0,8}(\d[\d.,]{2,6})", re.I),
}


def _num(s):
    d = re.sub(r"[.,\s]", "", str(s or ""))
    return int(d) if d.isdigit() else None


# Millimetre bounds for a road vehicle. Generous — a 24m road train is legal
# somewhere — but they exclude the pairing failures we actually saw.
_DIM_BOUNDS = {"panjang": (2000, 25000), "lebar": (1000, 3500), "tinggi": (1000, 5000)}


def _dims_plausible(parts):
    for axis, (lo, hi) in _DIM_BOUNDS.items():
        v = parts.get(axis)
        if v is None or not (lo <= v <= hi):
            return False
    # A vehicle is longer than it is wide. "26000 x 26000" is one number read twice.
    return parts["panjang"] > parts["lebar"] and parts["panjang"] > parts["tinggi"]

# 7790 CC | ISI SILINDER 7790 | KUBIKASI: 7.790 cc
_CC_LABELLED = re.compile(
    r"(?:ISI\s*SILINDER|KUBIKASI|SILINDER|CYLINDER|CC)\D{0,6}([\d.,]{3,7})", re.I)
_CC_SUFFIX = re.compile(r"\b([\d.,]{3,7})\s*(?:CC|CM3|CM³)\b", re.I)


_MONTH_NAMES = {
    "JAN": 1, "FEB": 2, "PEB": 2, "MAR": 3, "APR": 4, "MEI": 5, "MAY": 5,
    "JUN": 6, "JUL": 7, "AGU": 8, "AGT": 8, "AUG": 8, "SEP": 9, "OKT": 10,
    "OCT": 10, "NOV": 11, "DES": 12, "DEC": 12,
}
_KIR_VALID_LABEL = re.compile(r"MASA\s*BERLAKU|BERLAKU\s*S(?:AMPAI|/D)|VALID\s*UNTIL", re.I)
# "26JUL1 2023" — Paddle glues the day to the month and sprinkles a stray digit
_NAMED_DATE = re.compile(r"(\d{1,2})\s*([A-Z]{3})[A-Z]*\s*\d?\s*(\d{4})", re.I)


def _deaccent(s: str) -> str:
    # OCR emits 'berłaku' (a Polish l-stroke) for 'berlaku'; a label match must
    # not hinge on which Unicode letter the recognizer happened to pick.
    return (str(s or "").replace("ł", "l").replace("Ł", "L")
            .replace("İ", "I").replace("ı", "i"))


def extract_kir_validity(lines: List[str], fields: Dict[str, Any]) -> Dict[str, Any]:
    """Read the KIR's expiry, which is printed as a NAMED month ("26 JUL 2023").

    The generic date-shape path expected digits and produced "30-12-1899" — the
    spreadsheet epoch, i.e. a parse of nothing. The date was on the card all
    along, one line below a label OCR'd as "Masa berłaku uji berkala".
    """
    lines = [_deaccent(l or "") for l in (lines or [])]
    for i, ln in enumerate(lines):
        if not _KIR_VALID_LABEL.search(ln):
            continue
        for cand in (ln, *lines[i + 1:i + 7]):
            m = _NAMED_DATE.search(cand)
            if m:
                mon = _MONTH_NAMES.get(m.group(2).upper())
                if not mon:
                    continue
                dd, yy = int(m.group(1)), int(m.group(3))
                if not (1 <= dd <= 31) or not (_DATE_WINDOW[0] <= yy <= _DATE_WINDOW[1]):
                    continue
                val = f"{dd:02d}-{mon:02d}-{yy:04d}"
                _set(fields, "valid_until", val, 0.85, "kir_named_date", overwrite=True)
                _set(fields, "masa_berlaku", val, 0.85, "kir_named_date", overwrite=True)
                logger.info("KIR validity %r -> %s", cand.strip(), val)
                return fields
    return fields


def extract_kir_spec_fields(lines: List[str], fields: Dict[str, Any]) -> Dict[str, Any]:
    fields = extract_kir_validity(lines or [], fields)
    """hasil_uji / dimensi / kubikasi — required by the spec, emitted by nobody."""
    fields = drop_plate_scraped_from_a_longer_token(lines or [], fields)
    text = " | ".join(l for l in (lines or []) if l)

    # --- pass / not pass
    if _FAIL_PAT.search(text):
        m = _FAIL_PAT.search(text)
        _set(fields, "hasil_uji", m.group(0).upper().strip(), 0.9, "kir_result_negated")
        _set(fields, "hasil_uji_normalized", "FAIL", 0.9, "kir_result_negated")
    elif _PASS_PAT.search(text):
        m = _PASS_PAT.search(text)
        _set(fields, "hasil_uji", m.group(0).upper().strip(), 0.85, "kir_result")
        _set(fields, "hasil_uji_normalized", "PASS", 0.85, "kir_result")
    else:
        # A KIR card does not PRINT the word "lulus" — the certificate itself IS
        # the result. Nothing in the OCR text of KIR_standard/KIR_bad says pass
        # or fail, yet a human labelling these cards writes PASS, because an
        # unexpired KIR was only issued after the vehicle passed its test.
        #
        # So this value is REASONED, not READ, and it says so: the provenance
        # records the basis and the confidence is deliberately below anything
        # OCR produces. A reader must be able to tell "the card says so" from
        # "we concluded it" — on a truck safety certificate that difference is
        # the whole ballgame. If a failure word ever does appear, the branch
        # above wins and this never runs.
        expiry = fields.get("valid_until") or fields.get("masa_berlaku")
        expiry_val = expiry.get("value") if isinstance(expiry, dict) else expiry
        if expiry_val:
            fields["hasil_uji_normalized"] = {
                "value": "PASS",
                "confidence": 0.6,
                "provenance": {
                    "method": "inferred_from_validity",
                    "basis": (f"valid KIR certificate, expiry {expiry_val}, "
                              f"no failure wording on the card"),
                    "inferred": True,
                },
            }
            logger.info("hasil_uji inferred PASS from valid certificate (expiry %s)",
                        expiry_val)

    # --- dimensions (see _DIM_CARGO above for why this is not a one-liner)
    # The cargo tub is a real field, just not the one the spec asks for. Capture
    # it under its own name so it can never be mistaken for the vehicle's size.
    cargo = _DIM_CARGO.search(text)
    if cargo:
        _set(fields, "dimensi_bak_muatan",
             f"{cargo.group(1)} x {cargo.group(2)} x {cargo.group(3)}",
             0.8, "kir_dim_cargo")

    parts = {}
    for key, pat in _DIM_ROW.items():
        for ln in lines or []:
            if re.search(r"BAK\s*MUATAN|TANGKI", ln, re.I):
                continue  # never read the vehicle's size off the cargo-tub row
            m = pat.search(ln)
            if m and _num(m.group(1)):
                parts[key] = _num(m.group(1))
                break

    # Geometry (spatial_pairing) runs BEFORE this and pairs each label with the
    # number beside it — which text order cannot do, because OCR emits "Panjang"
    # and "6000" as separate lines. Prefer its answers.
    for key in ("panjang", "lebar", "tinggi"):
        if key in parts:
            continue
        rec = fields.get(key)
        v = _num(rec.get("value") if isinstance(rec, dict) else rec)
        if v:
            parts[key] = v

    # Geometry can pair a label with the WRONG number (it once produced
    # "9 x 2050 x 7500 mm" — a 9mm-long truck). Every axis is a millimetre
    # figure on a road vehicle, and a vehicle is always longer than it is wide.
    # An implausible triple is a pairing failure, not a measurement: drop it.
    if len(parts) == 3 and not _dims_plausible(parts):
        logger.info("rejecting implausible KIR dimensions: %r", parts)
        parts = {}

    if len(parts) == 3:
        _set(fields, "dimensi",
             f"{parts['panjang']} x {parts['lebar']} x {parts['tinggi']} mm",
             0.85, "kir_dim_rows")
    elif parts:
        # Some axes legible, not all. Report what was actually read; do NOT
        # complete the triple from the only AxBxC string on the page, because
        # that string is the cargo tub and the answer would be confidently wrong.
        _set(fields, "dimensi_partial",
             ", ".join(f"{k}={v}" for k, v in sorted(parts.items())), 0.5,
             "kir_dim_partial")

    # --- kubikasi / engine displacement
    for pat, method in ((_CC_LABELLED, "kir_cc_labelled"), (_CC_SUFFIX, "kir_cc_suffix")):
        m = pat.search(text)
        if m:
            raw = m.group(1)
            digits = re.sub(r"[.,]", "", raw)
            if digits.isdigit() and 500 <= int(digits) <= 30000:
                _set(fields, "kubikasi", f"{int(digits)} cc", 0.8, method)
                break

    # Geometry can also fill `kubikasi`, and it once paired the label with "0.34".
    # No road vehicle has a 0.34cc engine — an out-of-range displacement is a
    # pairing failure, so drop it rather than ship it.
    rec = fields.get("kubikasi")
    v = rec.get("value") if isinstance(rec, dict) else rec
    if v is not None:
        cc = _num(re.sub(r"(?i)\s*(cc|cm3)\s*$", "", str(v)))
        if cc is None or not (500 <= cc <= 30000):
            logger.info("dropping implausible kubikasi: %r", v)
            fields.pop("kubikasi", None)
        elif not str(v).lower().endswith("cc"):
            fields["kubikasi"] = {"value": f"{cc} cc",
                                  "confidence": (rec.get("confidence", 0.7)
                                                 if isinstance(rec, dict) else 0.7),
                                  "provenance": {"method": "kir_cc_normalized"}}
    return fields


# ----------------------------------------------------------------- STNK

# On an STNK the closest thing to "type of registration" is JENIS
# (MOBIL BARANG = goods vehicle, MOBIL PENUMPANG = passenger).
# "MOBIL BARANG/BEBAN" is what the card actually says; stopping the vocabulary at
# "MOBIL BARANG" reported a value that is a truncation of the printed one.
# Some STNK layouts print the jenis ABBREVIATED ("MBRG" = Mobil Barang,
# "MPNG" = Mobil Penumpang), often glued to the body description
# ("MBRG/L. TRUCK BAK KA"). The abbreviations are specific 4-letter tokens, so
# matching them (and returning just the token, as the card prints it) is safe.
_STNK_JENIS = re.compile(
    r"\b(MOBIL\s*BARANG(?:\s*/\s*BEBAN)?|MOBIL\s*PENUMPANG|SEPEDA\s*MOTOR|"
    r"MOBIL\s*BUS|KENDARAAN\s*KHUSUS|MBRG|MPNG)\b",
    re.I)
_STNK_JENIS_LABEL = re.compile(r"^\s*JENIS\s*[:\-]?\s*(.+)$", re.I)


# WARNA is a closed vocabulary. OCR truncates it ("PUTI") and the text-order
# path glues neighbouring cells to it ("2) M/T BENST HITAM"). Recover the colour
# from the vocabulary instead of shipping the fragment.
_COLOURS = ["PUTIH", "HITAM", "MERAH", "BIRU", "KUNING", "HIJAU", "SILVER",
            "ABU-ABU", "COKELAT", "COKLAT", "ORANGE", "ORANYE", "UNGU", "EMAS",
            "KREM", "TOSCA", "MAROON", "GOLD", "BEIGE"]

# Tokens that prove the value came from the WRONG cell — fuel type, a label, a
# heading. The model field on an STNK is the one the text-order path fails on
# most often (it returned "BENSIN", "IFUEL/ENERGY SOURCES", "SEBAGAI TANDA").
_NOT_A_MODEL = re.compile(
    r"BENSIN|SOLAR|FUEL|ENERGY|SOURCE|SEBAGAI|TANDA|BUKTI|PELUNASAN|JENIS|"
    r"BAHAN\s*BAKAR|NOMOR|REGISTRASI|IDENTITAS", re.I)


def _clean_warna(value: str):
    """Return the colour named in `value`, or None if none is."""
    up = re.sub(r"[^A-Z ]", " ", str(value or "").upper())
    found = [c for c in _COLOURS if c.replace("-", "") in up.replace("-", "").replace(" ", "")]
    if found:
        # "ORANGE SILVER" is a real two-colour value; keep the order they appear.
        found.sort(key=lambda c: up.replace(" ", "").find(c.replace("-", "")))
        return " ".join(dict.fromkeys(found))
    tok = [t for t in up.split() if len(t) >= 4]
    for t in tok:
        for c in _COLOURS:
            # "PUTI" -> "PUTIH": a truncation, not a different colour
            if c.startswith(t) and len(t) >= len(c) - 2:
                return c
    return None


def sanitize_stnk(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop STNK values that provably came from the wrong cell.

    A wrong `model` is not a cosmetic problem: it is the field the customer
    calls "Truck's type". Returning the fuel type there, confidently, is worse
    than returning nothing — nothing gets reviewed.
    """
    if not isinstance(fields, dict):
        return fields

    rec = fields.get("warna")
    v = rec.get("value") if isinstance(rec, dict) else rec
    if v:
        colour = _clean_warna(v)
        if colour and colour != v:
            logger.info("warna %r -> %r (vocabulary)", v, colour)
            if isinstance(rec, dict):
                rec["value"] = colour
                rec.setdefault("provenance", {})["normalized"] = "colour_vocab"
            else:
                fields["warna"] = colour
        elif not colour:
            _drop(fields, "warna", v, "bukan warna yang dikenal")

    rec = fields.get("model")
    v = rec.get("value") if isinstance(rec, dict) else rec
    if v:
        s = str(v).strip()
        digits = sum(c.isdigit() for c in s)
        if (_NOT_A_MODEL.search(s)
                or len(s) > 24
                or (len(s) and digits / len(s) > 0.35)):
            _drop(fields, "model", s, "bukan model kendaraan yang masuk akal")
    return fields


# The card's own label comes out of OCR as "BERLAKUSAMPAD" — no space, and a D
# for the I. Demanding a clean "SAMPAI" matched the tax receipt's tidy label and
# missed the card's, which is the one document whose date the spec actually asks
# for. On an STNK, "BERLAKU" only ever introduces a validity date, so the word
# alone is the honest anchor.
_BERLAKU_LABEL = re.compile(r"BERLAKU", re.I)
_ANY_DATE = re.compile(r"(\d{1,2})\s*[-/. ]\s*(\d{1,2})\s*[-/. ]\s*(\d{4})")


def split_stnk_validity(lines: List[str], fields: Dict[str, Any]) -> Dict[str, Any]:
    """Tell the STNK card's expiry apart from the tax receipt's.

    A third of the customer's STNK photos show the card AND the annual tax
    receipt (`TANDA BUKTI PELUNASAN`) in one frame, and BOTH print `BERLAKU
    SAMPAI`. The pipeline took whichever it saw first — which was the receipt,
    so `13-06-2025` on the card was reported as `13-06-2023` from the slip.

    The card outlives the receipt by construction: registration runs five years,
    the tax stamp one. So of two BERLAKU SAMPAI dates, the later is the card's
    (`berlaku_sampai`, the spec's "Expiration") and the earlier is the tax
    stamp's (`tax_valid_to`). One date means one document: it is the card's.
    """
    lines = [l or "" for l in (lines or [])]
    found = []
    for i, ln in enumerate(lines):
        if not _BERLAKU_LABEL.search(ln):
            continue
        # OCR emits the label and its value as SEPARATE lines as often as not
        # ("BERLAKU SAMPAI" / "13-06-2025"), so a same-line regex found nothing
        # on the very photos this exists for. Look on the label's own line
        # first, then at the next two lines.
        for cand in (ln, *lines[i + 1:i + 3]):
            m = _ANY_DATE.search(cand)
            if not m:
                continue
            dd, mm, yy = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if not (_DATE_WINDOW[0] <= yy <= _DATE_WINDOW[1]) or not (1 <= mm <= 12) \
                    or not (1 <= dd <= 31):
                continue
            found.append(((yy, mm, dd), f"{dd:02d}-{mm:02d}-{yy:04d}"))
            break
    if not found:
        return fields
    found.sort()
    card = found[-1][1]
    receipt = found[0][1]
    _set(fields, "berlaku_sampai", card, 0.88, "stnk_card_validity", overwrite=True)
    if receipt != card:
        _set(fields, "tax_valid_to", receipt, 0.88, "tax_receipt_validity", overwrite=True)
        logger.info("two BERLAKU SAMPAI dates: card=%s receipt=%s", card, receipt)
    return fields


def extract_stnk_spec_fields(lines: List[str], fields: Dict[str, Any]) -> Dict[str, Any]:
    fields = split_stnk_validity(lines or [], fields)
    fields = drop_plate_scraped_from_a_longer_token(lines or [], fields)
    text = " | ".join(l for l in (lines or []) if l)
    m = _STNK_JENIS.search(text)
    if m:
        jenis = re.sub(r"\s+", " ", m.group(1)).upper()
        _set(fields, "jenis", jenis, 0.85, "stnk_jenis_vocab")
        _set(fields, "jenis_registrasi", jenis, 0.85, "stnk_jenis_vocab")
        # NB: fall through to sanitize_stnk() — returning here skipped it, which
        # is why warna kept shipping as "PUTI".
        return sanitize_stnk(fields)
    for ln in lines or []:
        m = _STNK_JENIS_LABEL.match(ln)
        if m and m.group(1).strip():
            val = m.group(1).strip().upper()
            _set(fields, "jenis", val, 0.6, "stnk_jenis_label")
            _set(fields, "jenis_registrasi", val, 0.6, "stnk_jenis_label")
            break
    return sanitize_stnk(fields)


# ------------------------------------------------------------- KTP spec

# The header of a KTP: "PROVINSI JAWA TENGAH" / "KABUPATEN BATANG". The
# customer's spec calls this "ID registration place" and boxes both lines; no
# extractor in this codebase emitted either of them.
_KTP_PROVINSI = re.compile(r"PROVINSI\s*([A-Z][A-Z .'-]{3,30})", re.I)
_KTP_KOTA = re.compile(r"(KABUPATEN|KOTA(?:\s*ADMINISTRASI)?)\s*([A-Z][A-Z .'-]{3,30})", re.I)
# The body of a KTP is full of words that follow the header shape; the header
# sits at the top, so only consider the first handful of lines.
_KTP_HEADER_LINES = 6


def extract_ktp_spec_fields(lines: List[str], fields: Dict[str, Any]) -> Dict[str, Any]:
    """Emit `provinsi` and `kota` — the KYC spec's "ID registration place"."""
    header = (lines or [])[:_KTP_HEADER_LINES]
    for ln in header:
        m = _KTP_PROVINSI.search(ln or "")
        if m:
            val = re.sub(r"\s+", " ", m.group(1)).strip().upper()
            _set(fields, "provinsi", f"PROVINSI {val}", 0.85, "ktp_header")
        m = _KTP_KOTA.search(ln or "")
        if m:
            kind = m.group(1).upper()
            val = re.sub(r"\s+", " ", m.group(2)).strip().upper()
            # report the header as printed — "KABUPATEN BATANG", "KOTA DEPOK".
            # Stripping the KABUPATEN prefix invented a value the card never shows.
            _set(fields, "kota", f"{kind} {val}".strip(), 0.85, "ktp_header")

    # DKI Jakarta prints the city on the second header line WITHOUT a
    # KABUPATEN/KOTA keyword ("JAKARTA SELATAN"), and OCR glues it
    # ("JAKARTASELATAN"), so the keyword regex above never fires. A top header
    # line whose despaced form is a known kota/kabupaten IS the city; the
    # gazetteer both confirms it and restores the spacing. Restricted to the
    # first few lines (above the NIK) so a body field can't masquerade as one.
    rec = fields.get("kota")
    if not (rec.get("value") if isinstance(rec, dict) else rec):
        try:
            from app.utils.id_reference import kabupaten_names
            despaced = {re.sub(r"[^A-Z]", "", k.upper()): k for k in kabupaten_names()}
            for ln in header[:4]:
                u = (ln or "").upper()
                if "PROVINSI" in u:
                    continue
                key = re.sub(r"[^A-Z]", "", u)
                if len(key) >= 6 and key in despaced:
                    _set(fields, "kota", despaced[key], 0.75, "ktp_header_gazetteer")
                    break
        except Exception:
            pass
    return fields


# ------------------------------------------------------ NIK validation

# A NIK is PP KK SS DDMMYY NNNN — a real province code, then the holder's birth
# date (day +40 when female). v1 shipped values like "0160706207225400" and
# "5555561306201956" as `nik`: digit runs scraped off a vehicle document, with
# no valid province and no valid date. A fabricated national ID number is the
# worst possible output — it is wrong, it looks right, and nobody reviews it.
_NIK_STRUCTURED = re.compile(
    r"^(?:1[1-9]|2[1-9]|3[1-6]|5[1-3]|6[1-5]|7[1-6]|8[1-2]|9[1-4])"
    r"\d{4}"
    r"(?:0[1-9]|[12]\d|3[01]|4[1-9]|[56]\d|7[01])"
    r"(?:0[1-9]|1[0-2])\d{2}\d{4}$")


def nik_is_structurally_valid(value: str) -> bool:
    return bool(_NIK_STRUCTURED.match(re.sub(r"\D", "", str(value or ""))))


def validate_nik(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop a `nik` that cannot be a real NIK.

    Dropping means the field lands in needs_review, which is the documented
    contract: unreadable fields become needs_review, never a guess.
    """
    if not isinstance(fields, dict) or "nik" not in fields:
        return fields
    rec = fields.get("nik")
    val = rec.get("value") if isinstance(rec, dict) else rec
    if val and not nik_is_structurally_valid(val):
        _drop(fields, "nik", val, "NIK tidak sah secara struktur (provinsi/tanggal)")
        fields.pop("id_number", None)  # KTP alias of nik
    return fields


# ------------------------------------------------------ plate validation

# The region code is the first block of an Indonesian plate and it is a CLOSED
# set. v2 shipped "FM 517 H" and "GC 415 V" as plates: both were scraped off the
# TYPE row ("FUSO FM 517 HRDK"), which has the same shape as a plate and no way
# to be told apart by shape alone. A code that does not exist is not a plate.
_PLATE_REGIONS = {
    "A", "AA", "AB", "AD", "AE", "AG", "B", "BA", "BB", "BD", "BE", "BG", "BH",
    "BK", "BL", "BM", "BN", "BP", "D", "DA", "DB", "DC", "DD", "DE", "DG", "DH",
    "DK", "DL", "DM", "DN", "DP", "DR", "DS", "DT", "DW", "E", "EA", "EB", "ED",
    "F", "G", "H", "K", "KB", "KH", "KT", "KU", "L", "M", "N", "P", "PA", "PB",
    "R", "S", "T", "W", "Z",
}
_PLATE_SHAPE = re.compile(r"^([A-Z]{1,2})([\s-]*)(\d{1,4})[\s-]*([A-Z]{1,3})$")

_PLATE_KEYS = ("nomor_polisi", "plate_number", "vehicle_id")


def plate_is_valid(value: str) -> bool:
    m = _PLATE_SHAPE.match(re.sub(r"\s+", " ", str(value or "")).strip().upper())
    if not m:
        return False
    region, sep, digits, _suffix = m.groups()
    if region not in _PLATE_REGIONS:
        return False
    # "S401RV" is a Daihatsu type code, not a plate: a real plate is written with
    # separators, and an unseparated one is only unambiguous at the full 4 digits
    # ("B9525SAI"). 3 digits glued to the region code is the type-row lookalike.
    if len(digits) < 4 and not sep.strip(" ") and " " not in sep:
        return False
    return True


_LABEL_WORDS = re.compile(r"NOMOR|POLISI|REGISTRASI|NOPOL|PLAT")

# A plate-shaped run anywhere in a line ("...:B 9437 SRU", "AD-9468-BV").
_PLATE_FIND = re.compile(r"(?<![A-Z0-9])([A-Z]{1,2})[\s-]?(\d{1,4})[\s-]?([A-Z]{1,3})(?![A-Z0-9])")


def recover_plate_from_lines(lines: List[str], fields: Dict[str, Any]) -> Dict[str, Any]:
    """Fill an EMPTY plate from a valid plate token in the raw OCR.

    The plate is printed large at the TOP of an STNK, far from its "NOMOR
    REGISTRASI" label; the label-geometry pairing grabbed a nearby fragment
    ("KA 2011"), validate_plate rightly dropped it (KA is no region), and the
    real, perfectly-read plate ("AD-9468-BV") was left on the floor. Geometry
    can't reach it, but the region code is a CLOSED set, so a shape+region scan
    of every line finds it. Only fills when no valid plate is present, and only
    when the card shows exactly ONE distinct valid plate (ambiguity -> review).
    """
    if not isinstance(fields, dict):
        return fields
    for key in _PLATE_KEYS:
        rec = fields.get(key)
        val = rec.get("value") if isinstance(rec, dict) else rec
        if val and plate_is_valid(val):
            return fields  # a good plate already stands; don't touch it

    tokens = []
    for ln in lines or []:
        for tok in str(ln).upper().split():
            t = re.sub(r"[^A-Z0-9]", "", tok)
            if t:
                tokens.append(t)

    found = []
    for ln in lines or []:
        u = re.sub(r"\s+", " ", str(ln).upper())
        for m in _PLATE_FIND.finditer(u):
            # a label-less scan has no geometry to lean on, so demand the full
            # 4-digit block (the modern standard): it rejects OCR noise like
            # "B 00 W" off a bad photo, which would otherwise turn a safe MISS
            # into a wrong plate — the worst field to ship on a KYC record
            if len(m.group(2)) != 4:
                continue
            cand = f"{m.group(1)} {m.group(2)} {m.group(3)}"
            if not plate_is_valid(cand):
                continue
            packed = re.sub(r"[^A-Z0-9]", "", cand)
            # not a slice of a longer code (type row "S401RV-SMPEJLTHF")
            if any(packed in tok and len(tok) >= len(packed) + 3
                   and not _LABEL_WORDS.search(tok) for tok in tokens):
                continue
            if cand not in found:
                found.append(cand)

    if len(found) == 1:
        fields["nomor_polisi"] = {"value": found[0], "confidence": 0.7,
                                  "provenance": {"method": "plate_scan"}}
    return fields


def drop_plate_scraped_from_a_longer_token(lines: List[str],
                                           fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop a 'plate' that is really a slice of a longer code in the OCR text.

    The type code reads `S401RV-SMPEJLTHF`; sliced by the plate regex it becomes
    `S 401 RV`, whose region letter (S) is perfectly real — no shape or
    vocabulary rule can reject it, and the TYPE row it came from was too garbled
    to extract, so there was no field to compare against either. But the code is
    right there in the raw OCR text.

    A genuine plate is a token on its own (`:B 9437 SRU`). A misfiled type code
    is always embedded inside something longer. So: if the plate only ever occurs
    INSIDE a longer alphanumeric run, it is not the plate.
    """
    if not isinstance(fields, dict):
        return fields
    # Split on WHITESPACE only, then strip punctuation inside each token: a type
    # code is hyphenated ("S401RV-SMPEJLTHF"), so splitting on the hyphen too
    # would leave the token exactly equal to the fake plate and hide the very
    # embedding we are looking for. A real plate arrives as separate tokens
    # (":B 9437 SRU" -> B / 9437 / SRU) and so is never embedded in one.
    tokens = []
    for ln in lines or []:
        for tok in str(ln).upper().split():
            tok = re.sub(r"[^A-Z0-9]", "", tok)
            if tok:
                tokens.append(tok)
    for key in _PLATE_KEYS:
        rec = fields.get(key)
        val = rec.get("value") if isinstance(rec, dict) else rec
        if not val:
            continue
        p = re.sub(r"[^A-Z0-9]", "", str(val).upper())
        if len(p) < 4:
            continue
        # the plate's own characters may be spread over several OCR tokens
        # (":B 9437 SRU" -> B / 9437 / SRU), so a plate that never appears whole
        # inside ONE longer token is fine.
        embedded = any(
            p in tok and len(tok) >= len(p) + 3 and not _LABEL_WORDS.search(tok)
            for tok in tokens
        )
        if embedded:
            _drop(fields, key, val, "potongan kode tipe kendaraan, bukan plat")
    return fields


def _plate_came_from_the_type_row(plate: str, fields: Dict[str, Any]) -> bool:
    """True if this 'plate' is really a slice of the vehicle's type code.

    `S401RV-BMRLJJHF BVAN` is a Daihatsu type code. Spaced out by OCR it reads
    `S 401 RV`, whose region letter (`S`, Surabaya) is perfectly real — so no
    shape or vocabulary rule can reject it. What gives it away is that it is
    sitting inside the TYPE row we also extracted. A plate is not a substring of
    the vehicle's type code; a misfiled type code always is.
    """
    p = re.sub(r"[^A-Z0-9]", "", str(plate or "").upper())
    if len(p) < 4:
        return False
    for src_key in ("tipe", "model", "brand", "nomor_rangka"):
        rec = fields.get(src_key)
        src = rec.get("value") if isinstance(rec, dict) else rec
        if not src:
            continue
        if p in re.sub(r"[^A-Z0-9]", "", str(src).upper()):
            return True
    return False


def validate_plate(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop a plate that cannot be one, or that was scraped off another row.

    Every one of the 17 human-labelled plates in the demo set survives this;
    every plate the pipeline invented fails it. A wrong plate is the single worst
    field to ship on a logistics KYC record — it names a different vehicle.
    """
    if not isinstance(fields, dict):
        return fields
    for key in _PLATE_KEYS:
        rec = fields.get(key)
        if rec is None:
            continue
        val = rec.get("value") if isinstance(rec, dict) else rec
        if not val:
            continue
        if not plate_is_valid(val):
            _drop(fields, key, val, "plat tidak sah: kode wilayah tidak ada")
        elif _plate_came_from_the_type_row(val, fields):
            _drop(fields, key, val, "plat terambil dari baris TYPE, bukan plat")
    return fields


# ------------------------------------------------------- date validation

# Any document in circulation carries a year in this window. "30-12-1899" is the
# spreadsheet epoch leaking through a date parser, not a date on the card.
_DATE_WINDOW = (2015, 2040)
_VALIDITY_KEYS = ("tax_valid_to", "valid_until", "masa_berlaku", "berlaku_sampai",
                  "expiry_date")


def _year_of(value: str) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", str(value or ""))
    return int(m.group(0)) if m else None


def validate_dates(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop a validity date whose year cannot belong to a document in use."""
    if not isinstance(fields, dict):
        return fields
    for key in _VALIDITY_KEYS:
        rec = fields.get(key)
        if rec is None:
            continue
        val = rec.get("value") if isinstance(rec, dict) else rec
        if not val:
            continue
        year = _year_of(val)
        if year is None or not (_DATE_WINDOW[0] <= year <= _DATE_WINDOW[1]):
            _drop(fields, key, val, "tahun di luar rentang dokumen berlaku")
    return fields


# ------------------------------------------- KTP cross-field validation

_SEX_VALUES = ("LAKI-LAKI", "PEREMPUAN")


def validate_jenis_kelamin(fields: Dict[str, Any]) -> Dict[str, Any]:
    """`jenis_kelamin` is a two-value vocabulary. Anything else is a misread.

    v2 shipped "A" and "LAKHUAKO" here. Both are the OCR of LAKI-LAKI falling
    apart; neither is a sex, and a KYC record cannot carry one.
    """
    if not isinstance(fields, dict):
        return fields
    rec = fields.get("jenis_kelamin")
    if rec is None:
        return fields
    val = rec.get("value") if isinstance(rec, dict) else rec
    if not val:
        return fields
    up = re.sub(r"[^A-Z]", "", str(val).upper())
    for canonical in _SEX_VALUES:
        target = canonical.replace("-", "")
        # accept a truncation/misread that is still closer to one value than the
        # other ("LAKILAK", "PEREMPUA"), reject a word that is neither
        if SequenceMatcher(None, up, target).ratio() >= 0.75:
            if val != canonical:
                logger.info("jenis_kelamin %r -> %r (vocabulary)", val, canonical)
                if isinstance(rec, dict):
                    rec["value"] = canonical
                    rec.setdefault("provenance", {})["normalized"] = "sex_vocab"
                else:
                    fields["jenis_kelamin"] = canonical
            return fields
    _drop(fields, "jenis_kelamin", val, "bukan LAKI-LAKI / PEREMPUAN")
    return fields


def reconcile_dob_with_nik(fields: Dict[str, Any]) -> Dict[str, Any]:
    """The NIK CONTAINS the date of birth. Use it — do not guess alongside it.

    Digits 7-12 of a NIK are DDMMYY, with 40 added to the day for a female
    holder. v2 shipped `tanggal_lahir: 2020-06-18` on a card whose own NIK says
    29-07-1994: the date was scraped from somewhere else on the document while
    the answer was sitting in a field we already validated.

    A structurally valid NIK is therefore authoritative: it CORRECTS the date
    rather than merely dropping it. With no valid NIK there is nothing to check
    against, and an implausible birth year is dropped to needs_review.
    """
    if not isinstance(fields, dict):
        return fields
    dob = fields.get("tanggal_lahir")
    dob_val = dob.get("value") if isinstance(dob, dict) else dob
    nik_rec = fields.get("nik")
    nik_val = nik_rec.get("value") if isinstance(nik_rec, dict) else nik_rec
    nik_digits = re.sub(r"\D", "", str(nik_val or ""))

    from_nik = None
    if len(nik_digits) == 16 and nik_is_structurally_valid(nik_digits):
        dd, mm, yy = (int(nik_digits[6:8]), int(nik_digits[8:10]), int(nik_digits[10:12]))
        if dd > 40:            # female: day is stored +40
            dd -= 40
        # A KTP holder is at least 17: a 2-digit year is last century unless it
        # lands in the past 17 years.
        century = 2000 if yy <= 8 else 1900
        from_nik = f"{dd:02d}-{mm:02d}-{century + yy:04d}"

    dob_year = _year_of(dob_val) if dob_val else None
    dob_plausible = dob_year is not None and 1920 <= dob_year <= 2009

    if from_nik:
        # The NIK only FILLS a date that is missing or impossible — it never
        # overwrites a plausible one. A NIK is 16 digits and a single misread
        # digit still passes the structural check, so a NIK-derived date is not
        # more trustworthy than the birth-date row itself: trusting it blindly
        # turned a correct 18-04-1993 into 10-01-1990.
        if not dob_plausible:
            logger.info("tanggal_lahir %r -> %r (from NIK)", dob_val, from_nik)
            if isinstance(dob, dict):
                dob["value"] = from_nik
                dob.setdefault("provenance", {})["method"] = "nik_embedded_dob"
            else:
                fields["tanggal_lahir"] = {
                    "value": from_nik, "confidence": 0.9,
                    "provenance": {"method": "nik_embedded_dob"}}
        elif not _dob_same_day(dob_val, from_nik):
            # Both are readable and they disagree: one of the two is a misread.
            # Keep the birth-date row (it is the field being asked for) but say
            # so, rather than silently picking a winner.
            logger.info("tanggal_lahir %r disagrees with NIK-embedded %r",
                        dob_val, from_nik)
            if isinstance(dob, dict):
                dob.setdefault("provenance", {})["nik_dob_conflict"] = from_nik
        return fields

    # No NIK to check against: a birth year outside a living adult's range is a
    # misread, not a birth date.
    if dob_val and not dob_plausible:
        _drop(fields, "tanggal_lahir", dob_val, "tahun lahir tidak masuk akal")
    return fields


def sex_from_nik(fields: Dict[str, Any]) -> Dict[str, Any]:
    """The NIK encodes the holder's sex: 40 is added to the birth DAY for a
    female holder. So a structurally valid NIK answers "Sex type" exactly.

    `jenis_kelamin` is the KTP field OCR mangles most ("LAKI-LAKI" came out as
    "A" and "LAKHUAKO"), and the vocabulary check correctly drops that garbage —
    leaving the field empty on cards whose NIK states the answer outright. Fill
    from the NIK only when the row itself is unreadable; never override a
    legible one.
    """
    if not isinstance(fields, dict):
        return fields
    rec = fields.get("jenis_kelamin")
    cur = rec.get("value") if isinstance(rec, dict) else rec
    if cur:
        return fields
    nik_rec = fields.get("nik")
    nik_val = nik_rec.get("value") if isinstance(nik_rec, dict) else nik_rec
    digits = re.sub(r"\D", "", str(nik_val or ""))
    if len(digits) != 16 or not nik_is_structurally_valid(digits):
        return fields
    day = int(digits[6:8])
    value = "PEREMPUAN" if day > 40 else "LAKI-LAKI"
    logger.info("jenis_kelamin <- %r (from NIK day=%d)", value, day)
    fields["jenis_kelamin"] = {
        "value": value, "confidence": 0.9,
        "provenance": {"method": "nik_embedded_sex"}}
    return fields


def _dob_same_day(a, b) -> bool:
    """Same day written either way round (10-07-1992 vs 1992-07-10)."""
    da, db = re.findall(r"\d+", str(a or "")), re.findall(r"\d+", str(b or ""))
    return len(da) == 3 and len(db) == 3 and sorted(da) == sorted(db)


# ------------------------------------------------------- name validation

def validate_nama(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop a name too short to be one. "NIN" is a fragment of a mangled row."""
    if not isinstance(fields, dict):
        return fields
    for key in ("nama", "name", "owner", "owner_name"):
        rec = fields.get(key)
        if rec is None:
            continue
        val = rec.get("value") if isinstance(rec, dict) else rec
        if not val:
            continue
        letters = re.sub(r"[^A-Za-z]", "", str(val))
        if len(letters) < 4:
            _drop(fields, key, val, "terlalu pendek untuk sebuah nama")
    return fields


# ------------------------------------------------------ the whole sweep

def validate_fields(doc_type: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Every cross-field/vocabulary check, in dependency order.

    Runs after the extractors and before derive_aliases(), so the aliases are
    copied from values that have already survived validation.
    """
    dt = (doc_type or "").upper()
    fields = validate_nik(fields)          # must precede the DOB/sex checks
    if dt == "KTP":
        fields = validate_jenis_kelamin(fields)
        fields = sex_from_nik(fields)      # only fills what the vocab check emptied
        fields = reconcile_dob_with_nik(fields)
    if dt in ("STNK", "KIR"):
        fields = validate_plate(fields)
    fields = validate_dates(fields)
    fields = validate_nama(fields)
    return fields


# ------------------------------------------------- label-residue sweep

def strip_label_residue(fields: Dict[str, Any]) -> Dict[str, Any]:
    """Drop any field whose value is just a label printed on the document.

    Last line of defence. If every stage failed to find a real value, the
    honest output is no value — downstream that becomes needs_review. Shipping
    `alamat: "NAME OF OWNER"` into a customer's KYC record is worse than
    shipping nothing, because nothing gets reviewed and a wrong value does not.
    """
    if not isinstance(fields, dict):
        return fields
    try:
        from app.parser.spatial_pairing import _is_label_residue
    except Exception:
        return fields
    for key in list(fields.keys()):
        rec = fields.get(key)
        val = rec.get("value") if isinstance(rec, dict) else rec
        if isinstance(val, str) and _is_label_residue(val):
            _drop(fields, key, val, "hanya teks label yang tercetak, bukan nilai")
    return fields


# ------------------------------------------------------------- aliases

def derive_aliases(doc_type: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """Make every alias a copy of its canonical field, for THIS document type.

    Runs LAST, after every extraction stage. An alias whose canonical came out
    empty is dropped rather than left holding a stale guess — a caller
    integrating against `vin_chassis` must never receive the label residue that
    `nomor_rangka` already corrected.
    """
    if not isinstance(fields, dict):
        return fields
    mapping = ALIASES.get((doc_type or "").upper())
    if not mapping:
        return fields
    for canonical, aliases in mapping.items():
        src = fields.get(canonical)
        src_val = src.get("value") if isinstance(src, dict) else src
        for alias in aliases:
            if alias == canonical:
                continue
            if not src_val:
                # Canonical is empty: an alias here could only be a stale
                # guess from the text-order path. Drop it.
                fields.pop(alias, None)
                continue
            if isinstance(src, dict):
                fields[alias] = dict(src)
                prov = dict(fields[alias].get("provenance") or {})
                prov["alias_of"] = canonical
                fields[alias]["provenance"] = prov
            else:
                fields[alias] = {"value": src_val, "confidence": 1.0,
                                 "provenance": {"alias_of": canonical}}
    return fields
