import pytest

from app.parser.stnk_parser.stnk_extractor import STNKExtractor
from app.models.schemas import ParserContext


def test_stnk_basic_fields():
    ext = STNKExtractor()
    lines = [
        "NAMA PEMILIK: SULAIMAN",
        "ALAMAT: JL. MELATI RAYA NO. 7",
        "B 1234 XYZ",
        "PAJAK BERLAKU S/D 31/12/2026",
    ]
    ctx = ParserContext(raw_lines=lines, debug=False)
    res = ext.parse(ctx)
    assert res["document_type"] == "STNK"
    f = res["fields"]
    assert f["plate_number"]["value"] == "B 1234 XYZ"
    assert f["owner_name"]["value"] == "SULAIMAN"
    assert f["address"]["value"].startswith("JL. MELATI RAYA")
    assert f["tax_valid_to"]["value"] == "31-12-2026"


def test_stnk_value_shape_fallback():
    from app.parser.stnk_parser.stnk_extractor import STNKExtractor
    from app.models.schemas import ParserContext

    ext = STNKExtractor()
    ctx = ParserContext(raw_lines=[
        "WWOER.NSTN",              # was: NOMOR RANGKA/NIK/VIN
        "MHKB3BA1JHK046596",
        "SLE.Mn",                  # was: NOMOR MESIN
        "K3MH09391",
    ], debug=False)
    res = ext.parse(ctx)
    f = res["fields"]
    assert f["nomor_rangka"]["value"] == "MHKB3BA1JHK046596"
    assert f["nomor_mesin"]["value"] == "K3MH09391"


def test_stnk_glued_label_owner():
    from app.parser.stnk_parser.stnk_extractor import STNKExtractor
    from app.models.schemas import ParserContext

    ext = STNKExtractor()
    ctx = ParserContext(raw_lines=["NAMAPEMILIK", ": KURNIA NINGRUM"], debug=False)
    res = ext.parse(ctx)
    assert res["fields"]["owner"]["value"] == "KURNIA NINGRUM"
