"""ISO 6346 shipping-container number validation.

Every container in international traffic (all Indonesian ports included)
carries an ISO 6346 code: 4 letters (owner + equipment category) +
6 digits (serial) + 1 check digit, e.g. CSQU3054383.

The check digit is computable: letters map to values 10..38 SKIPPING
multiples of 11 (A=10, B=12, ..., K=21, L=23, ...), digits map to
themselves; each of the first 10 characters is weighted 2^position;
sum mod 11 gives the check digit (a result of 10 wraps to 0).

This makes container numbers SELF-VERIFYING: an OCR misread is caught
by arithmetic, no registry lookup needed.
"""
import re
from typing import Dict, List, Optional

# A=10, skipping multiples of 11 (11, 22, 33)
_LETTER_VALUES = {}
_v = 10
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    if _v % 11 == 0:
        _v += 1
    _LETTER_VALUES[_c] = _v
    _v += 1

_RE_CONTAINER = re.compile(r"\b([A-Z]{3}[UJZ])\s*(\d{6})\s*(\d)\b")


def compute_check_digit(owner_serial: str) -> Optional[int]:
    """Check digit for the first 10 chars (4 letters + 6 digits)."""
    s = re.sub(r"\s", "", owner_serial.upper())
    if not re.fullmatch(r"[A-Z]{4}\d{6}", s):
        return None
    total = 0
    for i, ch in enumerate(s):
        val = _LETTER_VALUES[ch] if ch.isalpha() else int(ch)
        total += val * (2 ** i)
    return (total % 11) % 10


def validate_container_number(number: str) -> Dict:
    """Validate a full 11-character container number.

    Returns {number, valid, expected_check_digit, reason}.
    """
    s = re.sub(r"[\s-]", "", (number or "").upper())
    if not re.fullmatch(r"[A-Z]{4}\d{7}", s):
        return {"number": s, "valid": False, "expected_check_digit": None,
                "reason": "format_invalid"}
    expected = compute_check_digit(s[:10])
    actual = int(s[10])
    valid = expected == actual
    return {"number": f"{s[:4]} {s[4:10]} {s[10]}", "valid": valid,
            "expected_check_digit": expected,
            "reason": None if valid else "check_digit_mismatch"}


def find_container_numbers(text: str) -> List[Dict]:
    """Find and validate all container-shaped tokens in free text
    (e.g. OCR lines from a gate photo). Category letter must be U/J/Z
    per ISO 6346."""
    results = []
    seen = set()
    for m in _RE_CONTAINER.finditer((text or "").upper()):
        raw = m.group(1) + m.group(2) + m.group(3)
        if raw in seen:
            continue
        seen.add(raw)
        results.append(validate_container_number(raw))
    return results
