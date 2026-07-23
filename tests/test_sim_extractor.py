import pytest

from app.parser.sim_parser.sim_extractor import SIMExtractor
from app.models.schemas import ParserContext


def test_sim_extract_basic_fields():
    ext = SIMExtractor()
    lines = [
        "SIM C 12345678901234",
        "NAMA: BUDI",
        "ALAMAT: JL. MERDEKA 1",
        "GOL. DARAH: O",
        "BERLAKU S/D 01-01-2030",
    ]
    ctx = ParserContext(raw_lines=lines, debug=False)
    res = ext.parse(ctx)
    assert res["document_type"] == "SIM"
    f = res["fields"]
    assert f["sim_number"]["value"] == "12345678901234"
    assert f["name"]["value"] == "BUDI"
    assert f["address"]["value"].startswith("JL. MERDEKA")
    assert f["class"]["value"] == "C"
    assert f["blood_type"]["value"] == "O"
    assert f["valid_to"]["value"] == "01-01-2030"


def test_sim_label_next_line_fallback():
    ext = SIMExtractor()
    lines = [
        "NAMA:",
        "SRI WAHYUNI",
        "KELAS: B1",  # colloquial digit form
    ]
    ctx = ParserContext(raw_lines=lines, debug=False)
    res = ext.parse(ctx)
    f = res["fields"]
    assert f["name"]["value"] == "SRI WAHYUNI"
    # Canonical output is Roman BI — real SIMs never print B1/B2
    assert f["class"]["value"] == "BI"


def test_sim_class_standalone_roman_umum():
    # New-format cards print the class big next to the number, no label
    ext = SIMExtractor()
    lines = [
        "INDONESIA",
        "SURAT IZIN MENGEMUDI",
        "DRIVING LICENSE",
        "BII UMUM",
        "1427-8708-000059",
        "1. AGUS SETYAWAN",
    ]
    ctx = ParserContext(raw_lines=lines, debug=False)
    res = ext.parse(ctx)
    assert res["fields"]["class"]["value"] == "BII UMUM"


def test_sim_class_ocr_confusions_normalized():
    ext = SIMExtractor()
    for raw, want in (("GOLONGAN: B11 UMUM", "BII UMUM"), ("KELAS: B2", "BII"), ("KELAS: Bl", "BI")):
        ctx = ParserContext(raw_lines=["SURAT IZIN MENGEMUDI", raw], debug=False)
        res = ext.parse(ctx)
        assert res["fields"]["class"]["value"] == want, raw


def test_sim_class_single_letter_standalone_rejected():
    # A bare 'D' line without label context must not become a class
    ext = SIMExtractor()
    ctx = ParserContext(raw_lines=["SURAT IZIN MENGEMUDI", "D"], debug=False)
    res = ext.parse(ctx)
    assert "class" not in res["fields"]
