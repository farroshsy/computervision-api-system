"""STNK jenis (Type of reg.): some layouts print it abbreviated ('MBRG' =
Mobil Barang), often glued to the body description ('MBRG/L. TRUCK BAK KA')."""
from app.parser.spec_fields import extract_stnk_spec_fields


def jenis(fields):
    r = fields.get("jenis")
    return r.get("value") if isinstance(r, dict) else r


def test_abbreviated_mbrg_extracted():
    out = extract_stnk_spec_fields(["JENIS", "MBRG/L. TRUCK BAK KA"], {})
    assert jenis(out) == "MBRG"


def test_full_mobil_barang_still_extracted():
    out = extract_stnk_spec_fields(["JENIS : MOBIL BARANG"], {})
    assert jenis(out) == "MOBIL BARANG"


def test_mpng_abbreviation():
    out = extract_stnk_spec_fields(["MPNG/MINIBUS"], {})
    assert jenis(out) == "MPNG"


def test_no_jenis_stays_absent():
    out = extract_stnk_spec_fields(["NOMOR REGISTRASI", "B 1234 XY"], {})
    assert jenis(out) is None
