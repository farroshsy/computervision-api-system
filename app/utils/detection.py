"""Document type auto-detection utilities.

Weighted-scoring detector for Indonesian documents (KTP, SIM, STNK, KIR).

Design (replaces the old first-match substring rules):
- Every document type has a list of weighted markers (keywords and regex
  patterns). All types are scored; the best-scoring type wins only if it
  reaches a minimum score AND leads the runner-up by a margin. Otherwise
  UNKNOWN is returned so callers can ask the user instead of guessing.
- Keywords are matched with word boundaries ("KIR" no longer matches
  "KIRIM" or "SEKIRA").
- Keyword matching also runs against a "shadow" copy of the text where
  common OCR digit/letter confusions are folded back to letters
  (0->O, 1->I, 5->S, 8->B, 2->Z, 6->G), so "N1K"/"PR0VINSI" still count.
  Digit patterns (NIK, plate, SIM number) run on the original text only.
"""
import re
from typing import Dict, List, Optional, Tuple

from app.schemas.request_models import DocumentType

# Minimum score the winner must reach, and minimum lead over the runner-up.
MIN_SCORE = 3.0
MIN_MARGIN = 1.0

# Digit -> letter folds for OCR-noise-tolerant keyword matching.
_SHADOW_TABLE = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "2": "Z", "6": "G"})

# Strong digit patterns (run on original uppercased text, not the shadow).
_RE_NIK16 = re.compile(r"(?<!\d)\d{4}[ .-]?\d{4}[ .-]?\d{4}[ .-]?\d{4}(?!\d)")

# A NIK is not "any 16 digits" — it is PP KK SS DDMMYY NNNN: a real province
# code, then the holder's birth date (day +40 when female). An STNK is full of
# long digit runs (chassis, engine, tax numbers), and scoring those as a NIK
# made KTP score 3.0 on vehicle documents — which is how a lone STNK got split
# into "STNK + KTP" with a fabricated NIK. Structure, not length.
_RE_NIK_STRUCTURED = re.compile(
    r"(?<!\d)"
    r"(?:1[1-9]|2[1-9]|3[1-6]|5[1-3]|6[1-5]|7[1-6]|8[1-2]|9[1-4])"  # province 11-94
    r"\d{4}"                                                        # kabupaten + kecamatan
    r"(?:0[1-9]|[12]\d|3[01]|4[1-9]|[56]\d|7[01])"                  # day, +40 if female
    r"(?:0[1-9]|1[0-2])"                                            # month
    r"\d{2}"                                                        # year
    r"\d{4}"                                                        # serial
    r"(?!\d)")
_RE_SIM_NO = re.compile(r"(?<!\d)\d{4}[ -]?\d{4}[ -]?\d{6}(?!\d)")
_RE_PLATE = re.compile(r"\b[A-Z]{1,2}\s?\d{1,4}\s?[A-Z]{1,3}\b")

# Keyword markers: (regex-ready keyword, weight). Multi-word markers use \s+
# between words so line joins and double spaces both match.
_KEYWORD_MARKERS: Dict[DocumentType, List[Tuple[str, float]]] = {
    DocumentType.KTP: [
        (r"KARTU\s+TANDA\s+PENDUDUK", 4.0),
        (r"NIK", 3.0),
        (r"KEWARGANEGARAAN", 2.0),
        (r"STATUS\s+PERKAWINAN", 2.0),
        (r"KEL(?:URAHAN)?\s*/?\s*DESA", 2.0),
        (r"SEUMUR\s+HIDUP", 2.0),
        (r"PROVINSI", 2.0),
        (r"BERLAKU\s+HINGGA", 1.0),
        (r"KECAMATAN", 1.0),
        (r"KABUPATEN|KOTA", 1.0),
        (r"GOL\.?\s*DARAH", 1.0),
        (r"AGAMA", 1.0),
    ],
    DocumentType.SIM: [
        (r"SURAT\s+IZIN\s+MENGEMUDI", 4.0),
        (r"IZIN\s+MENGEMUDI", 3.0),
        (r"DRIVING\s+LICEN[SC]E", 3.0),
        (r"SIM", 2.0),
        (r"POLRI|KEPOLISIAN", 2.0),
        (r"BERLAKU\s*S\s*/?\s*D", 1.0),
    ],
    DocumentType.STNK: [
        (r"SURAT\s+TANDA\s+NOMOR\s+KENDARAAN", 4.0),
        (r"TANDA\s+NOMOR\s+KENDARAAN", 3.0),
        (r"STNK", 3.0),
        (r"BBN\s*-?\s*KB|SWDKLLJ", 3.0),
        (r"PKB", 3.0),
        (r"MASA\s+BERLAKU\s+PAJAK", 2.0),
        (r"NO(?:MOR)?\.?\s+POLISI|NRKB", 2.0),
        (r"NO(?:MOR)?\.?\s+RANGKA", 1.0),
        (r"NO(?:MOR)?\.?\s+MESIN", 1.0),
        (r"MERK|TIPE", 0.5),
    ],
    DocumentType.KIR: [
        (r"PENGUJIAN\s+KENDARAAN\s+BERMOTOR", 4.0),
        (r"UJI\s+BERKALA", 4.0),
        (r"PERIODIC\s+INSPECTION|INSPECTION\s+CARD", 3.0),
        (r"PEMILIK\s+KENDARAAN\s+BERMOTOR", 2.0),
        (r"BUKU\s+UJI|KARTU\s+UJI", 3.0),
        (r"NO(?:MOR)?\.?\s+UJI", 3.0),
        (r"DAYA\s+ANGKUT", 3.0),
        (r"KIR", 2.0),
        (r"(?:TGL|TANGGAL|MASA)\.?\s+UJI", 2.0),
        (r"JBB|JBI", 2.0),
        (r"DISHUB|PERHUBUNGAN", 2.0),
        (r"NO(?:MOR)?\.?\s+RANGKA", 1.0),
        (r"NO(?:MOR)?\.?\s+MESIN", 1.0),
    ],
}

# Digit-pattern markers: (compiled regex, weight, marker label).
_PATTERN_MARKERS: Dict[DocumentType, List[Tuple[re.Pattern, float, str]]] = {
    DocumentType.KTP: [
        (_RE_NIK_STRUCTURED, 3.0, "NIK_STRUCTURED"),
        # A 16-digit run alone is weak evidence: every vehicle document has
        # digit runs that long. Not enough on its own to make a KTP.
        (_RE_NIK16, 0.5, "NIK_16_DIGITS"),
    ],
    DocumentType.SIM: [(_RE_SIM_NO, 2.0, "SIM_NUMBER_FORMAT")],
    DocumentType.STNK: [(_RE_PLATE, 1.0, "PLATE_NUMBER_FORMAT")],
    DocumentType.KIR: [],
}


def _score_document_types(ocr_lines: List[str]) -> Dict[DocumentType, Dict]:
    """Score every document type against the OCR text.

    Returns {doc_type: {"score": float, "markers": [str, ...]}}.
    """
    text = " ".join((ln or "").strip() for ln in (ocr_lines or [])).upper()
    text = re.sub(r"\s+", " ", text)
    shadow = text.translate(_SHADOW_TABLE)

    results: Dict[DocumentType, Dict] = {}
    for doc_type, markers in _KEYWORD_MARKERS.items():
        score = 0.0
        matched: List[str] = []
        for kw, weight in markers:
            # PaddelOCR quirk #1: spaces between words are often dropped
            # ("SURATIZINMENGEMUDI"), so multi-word markers match with or
            # without whitespace. Quirk #2: glued neighbours defeat \b
            # ("LULUSUJIBERKALA" hides UJI BERKALA behind a word boundary),
            # so long/multi-word markers match as plain substrings; only
            # short single-word markers (KIR, SIM, NIK...) keep \b to avoid
            # firing inside unrelated words.
            body = kw.replace(r"\s+", r"\s*")
            is_multiword = r"\s+" in kw or r"\s*" in kw
            if is_multiword or len(kw) >= 8:
                pattern = "(?:" + body + ")"
            else:
                pattern = r"\b(?:" + body + r")\b"
            if re.search(pattern, text) or re.search(pattern, shadow):
                score += weight
                matched.append(kw)
        for rx, weight, label in _PATTERN_MARKERS.get(doc_type, []):
            if rx.search(text):
                score += weight
                matched.append(label)
        results[doc_type] = {"score": score, "markers": matched}
    return results


def detect_document_type_detailed(ocr_lines: List[str]) -> Dict:
    """Detect document type with full scoring detail.

    Returns a dict:
      - doc_type: DocumentType (UNKNOWN when below threshold or ambiguous)
      - scores: {type_name: score} for all four types
      - matched_markers: markers that fired for the winning type
      - confidence: 0.0-1.0 advisory signal (score and margin based)
    """
    results = _score_document_types(ocr_lines)
    ranked = sorted(results.items(), key=lambda kv: kv[1]["score"], reverse=True)
    best_type, best = ranked[0]
    runner_score = ranked[1][1]["score"] if len(ranked) > 1 else 0.0
    margin = best["score"] - runner_score

    if best["score"] >= MIN_SCORE and margin >= MIN_MARGIN:
        doc_type = best_type
        confidence = min(1.0, (best["score"] / 8.0) * 0.7 + (min(margin, 4.0) / 4.0) * 0.3)
    else:
        doc_type = DocumentType.UNKNOWN
        confidence = 0.0

    return {
        "doc_type": doc_type,
        "scores": {dt.value: round(r["score"], 2) for dt, r in results.items()},
        "matched_markers": list(best["markers"]) if doc_type != DocumentType.UNKNOWN else [],
        "confidence": round(confidence, 3),
    }


def detect_document_type(ocr_lines: List[str]) -> DocumentType:
    """Detect document type from OCR lines (KTP, SIM, STNK, KIR, or UNKNOWN)."""
    return detect_document_type_detailed(ocr_lines)["doc_type"]


def detect_type_mismatch(declared: str, ocr_lines: List[str]) -> Optional[str]:
    """Return the detected type when the photo confidently CONTRADICTS the
    declared type; None when there is no contradiction.

    Contradiction requires all three: detection is confident of a
    DIFFERENT type, it is not UNKNOWN (blur must never trigger this),
    and the declared type's own score is weak (a wallet photo containing
    the declared document alongside another one is not a mismatch).

    Callers use this when the type came from a database column, an admin
    picking a dropdown, or a driver upload slot — the photo may simply be
    in the wrong slot, which is a re-request situation, not a rejection.
    """
    det = detect_document_type_detailed(ocr_lines or [])
    det_type = det["doc_type"].value
    declared_up = (declared or "").upper()
    declared_score = float((det.get("scores") or {}).get(declared_up, 0.0))
    if det_type not in ("UNKNOWN", declared_up) and declared_score < MIN_SCORE:
        return det_type
    return None
