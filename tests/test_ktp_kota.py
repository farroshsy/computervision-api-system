"""KTP 'Reg. city' (kota). DKI Jakarta prints the city on the second header
line with NO KABUPATEN/KOTA keyword ('JAKARTA SELATAN'); OCR glues it."""
from app.parser.spec_fields import extract_ktp_spec_fields


def kota(fields):
    r = fields.get("kota")
    return r.get("value") if isinstance(r, dict) else r


def test_dki_city_without_keyword_via_gazetteer():
    out = extract_ktp_spec_fields(["PROVINSIDKIJAKARTA", "JAKARTASELATAN", "NIK 3174..."], {})
    assert kota(out) == "JAKARTA SELATAN"


def test_kabupaten_keyword_still_wins():
    out = extract_ktp_spec_fields(["PROVINSI JAWA TENGAH", "KABUPATEN BATANG"], {})
    assert kota(out) == "KABUPATEN BATANG"


def test_province_line_not_taken_as_city():
    # 'PROVINSI ...' must never be picked as the city even if it despaces oddly
    out = extract_ktp_spec_fields(["PROVINSI DKI JAKARTA"], {})
    assert kota(out) is None


def test_no_city_when_no_gazetteer_match():
    out = extract_ktp_spec_fields(["PROVINSI DKI JAKARTA", "ZZQWERTY NONSENSE"], {})
    assert kota(out) is None
