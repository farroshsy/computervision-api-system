import re
from typing import Optional, Tuple
from datetime import datetime


def _only_digits(s: str) -> str:
    return re.sub(r"\D+", "", s or "")


def normalize_nik(value: Optional[str]) -> Optional[str]:
    """Normalize Indonesian NIK to a 16-digit string if plausible.
    Rules (basic):
    - Strip all non-digits
    - Must be 16 digits
    - Not all digits identical
    - Positions 7-12 encode date of birth as DDMMYY; for females, DD is +40
    - Month 01..12; Day 01..31 (or 41..71 for female)
    Returns normalized 16-digit string or None if invalid.
    """
    if not value:
        return None
    digits = _only_digits(value)
    if len(digits) != 16:
        return None
    if len(set(digits)) == 1:
        return None
    # Date segment
    try:
        dd = int(digits[6:8])
        mm = int(digits[8:10])
        yy = int(digits[10:12])
        if not (1 <= mm <= 12):
            return None
        day = dd - 40 if dd > 40 else dd
        if not (1 <= day <= 31):
            return None
        # Best-effort date validation (assume 1900..2099). We don't infer century strictly here.
        century = 2000 if yy <= int(datetime.now().strftime("%y")) else 1900
        _ = datetime(century + yy, mm, day)
    except Exception:
        return None
    return digits


def normalize_dob(value: Optional[str]) -> Optional[str]:
    """Normalize a date-of-birth string to ISO format YYYY-MM-DD.
    Accepts common variations like DD-MM-YYYY, DD/MM/YYYY, YYYY-MM-DD, etc.
    Returns ISO string or None if invalid.
    """
    if not value:
        return None
    s = (value or "").strip()
    if not s:
        return None
    # Try ISO first
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d", "%d %m %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Try extracting with regex (DD non-digit MM non-digit YYYY)
    m = re.search(r"\b(\d{1,2})\D(\d{1,2})\D(\d{4})\b", s)
    if m:
        try:
            d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
            dt = datetime(y, mth, d)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
    return None


def validate_nik_basic(value: Optional[str]) -> Tuple[bool, str]:
    """Basic validity check for NIK. Returns (is_valid, reason_or_empty)."""
    normalized = normalize_nik(value)
    if not normalized:
        return False, "nik_invalid_format"
    return True, ""


# --- Vehicle plate normalization ---
_PLATE_RE = re.compile(r"^([A-Z]{1,2})\s*(\d{1,4})\s*([A-Z]{1,3})?$", re.IGNORECASE)


def normalize_plate(value: Optional[str]) -> Optional[str]:
    """Normalize Indonesian license plate formats.
    Expected pattern: AA 1234 ABC (prefix 1-2 letters, 1-4 digits, optional 1-3 letters)
    Returns normalized 'AA 1234 ABC' or None if invalid.
    """
    if not value:
        return None
    s = re.sub(r"[^A-Za-z0-9 ]+", " ", value).upper()
    s = re.sub(r"\s+", " ", s).strip()
    m = _PLATE_RE.match(s)
    if not m:
        return None
    p1, num, suf = m.group(1).upper(), str(int(m.group(2))), (m.group(3).upper() if m.group(3) else None)
    if len(num) > 4:
        return None
    return f"{p1} {num}{(' ' + suf) if suf else ''}".strip()


# --- Chassis/VIN and engine numbers ---
def normalize_chassis(value: Optional[str]) -> Optional[str]:
    """Normalize chassis/VIN-like strings: uppercase alphanumeric, length 8..20.
    Returns cleaned value or None if implausible.
    """
    if not value:
        return None
    s = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if not (8 <= len(s) <= 20):
        return None
    return s


def normalize_engine(value: Optional[str]) -> Optional[str]:
    """Normalize engine number: uppercase alphanumeric, length 6..20."""
    if not value:
        return None
    s = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    if not (6 <= len(s) <= 20):
        return None
    return s


# --- Expiry date normalization (e.g., SIM expiry, STNK masa berlaku) ---
_ID_MONTHS = {
    "JANUARI": 1, "FEBRUARI": 2, "MARET": 3, "APRIL": 4, "MEI": 5,
    "JUNI": 6, "JULI": 7, "AGUSTUS": 8, "SEPTEMBER": 9, "OKTOBER": 10,
    "NOVEMBER": 11, "DESEMBER": 12,
    # bilingual cards (KIR) print English month names too
    "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "MAY": 5, "JUNE": 6,
    "JULY": 7, "AUGUST": 8, "OCTOBER": 10, "DECEMBER": 12,
}


def normalize_expiry_date(value: Optional[str]) -> Optional[str]:
    """Normalize expiry date to ISO YYYY-MM-DD.
    Accepts: YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, MM/YYYY (assumes day 01),
    and Indonesian month names as printed on KIR cards ("26 JULI 2023").
    """
    if not value:
        return None
    s = (value or "").strip()
    # Indonesian month-name format first (strptime can't parse it)
    m_id = re.match(r"^(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})$", s)
    if m_id and m_id.group(2).upper() in _ID_MONTHS:
        try:
            dt = datetime(int(m_id.group(3)), _ID_MONTHS[m_id.group(2).upper()], int(m_id.group(1)))
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d", "%d %m %Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            continue
    # MM/YYYY -> assume first day of month
    m = re.match(r"^(\d{1,2})\s*/\s*(\d{4})$", s)
    if m:
        try:
            mm, yyyy = int(m.group(1)), int(m.group(2))
            dt = datetime(yyyy, mm, 1)
            return dt.strftime("%Y-%m-%d")
        except Exception:
            return None
    return None


# --- RT/RW normalization ---
_RTRW_RE = re.compile(r"R\s*T\s*[.:]?\s*(\d{1,3}).{0,5}R\s*W\s*[.:]?\s*(\d{1,3})", re.IGNORECASE)


def normalize_rt_rw(value: Optional[str]) -> Optional[str]:
    """Normalize text containing RT/RW into 'RT XX/RW YY' with zero-padded 2 digits.
    Returns normalized string or None if patterns not found.
    """
    if not value:
        return None
    s = value.upper()
    m = _RTRW_RE.search(s)
    if not m:
        return None
    rt = int(m.group(1))
    rw = int(m.group(2))
    return f"RT {rt:02d}/RW {rw:02d}"
