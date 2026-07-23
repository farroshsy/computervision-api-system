"""
Shared constants for KTP parser extractors: street cues, admin tokens, OCR typo maps,
and abbreviation normalization patterns.
"""
from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple

# Street/address cues commonly present in Indonesian addresses
STREET_CUES: Set[str] = {
    'JL', 'JLN', 'JALAN', 'GG', 'GANG', 'NO', 'NO.', 'NOMOR', 'BLOK', 'KAV'
}

# Abbreviation normalization maps
ABBREVIATIONS_DEBUG: Dict[str, str] = {
    r'\bJLN\.?\b': 'JALAN',
    r'\bJL\.?\b': 'JALAN',
    r'\bJALAN\b': 'JALAN',
    r'\bJEND\.?\b': 'JENDERAL',
    r'\bNOMOR\b': 'NO',
    r'\bNO\.?\b': 'NO',
    r'\bKAV\.?\b': 'KAV',
    r'\bRT\.?\b': 'RT',
    r'\bRW\.?\b': 'RW',
    r'\bBLOK\.?\b': 'BLOK',
}

ABBREVIATIONS_NORMAL: Dict[str, str] = {
    r'\bJLN\b': 'JL.',
    r'\bJLN\.\b': 'JL.',
    r'\bJL\b': 'JL.',
    r'\bJL\.\b': 'JL.',
    r'\bNOMOR\b': 'NO.',
    r'\bNO\b': 'NO.',
    r'\bRT\.?\b': 'RT',
    r'\bRW\.?\b': 'RW',
    r'\bKAV\.?\b': 'KAV',
    r'\bBLOK\.?\b': 'BLOK',
}

# Common person/street name OCR typos found in addresses (regex, replacement)
NAME_TYPO_PATTERNS: List[Tuple[str, str]] = [
    (r'\bH\s*\.?\s*ASYIM\b', 'HASYIM'),
    (r'\bHASYM\b', 'HASYIM'),
    (r'\bHASHYM\b', 'HASYIM'),
    (r'\bHASIM\b', 'HASYIM'),
]

# Administrative/province tokens to avoid in locality fields
ADMIN_GEO_TOKENS: Set[str] = {
    'PROV', 'PROVINSI', 'PROPINSI', 'BANTEN', 'JAWA', 'JATENG', 'JABAR', 'JATIM',
    'SUMATERA', 'KALIMANTAN', 'SULAWESI', 'PAPUA', 'MALUKU', 'NUSA', 'TENGGARA'
}

# Substring regex to catch merged forms like 'APHOVINBBANTEN'
ADMIN_GEO_SUBSTRING_RE = re.compile(
    r'(PROV|PROVIN|PROVINSI|BANTEN|JAWA|SUMATERA|KALIMANTAN|SULAWESI|PAPUA|MALUKU|NUSATENGGARA|NUSA|TENGGARA)'
)
