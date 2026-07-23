from app.models.schemas import ParserContext
from app.parser.kir_parser.kir_extractor import KIRExtractor


def test_kir_parser_basic_fields():
    lines = [
        "DINAS PERHUBUNGAN KOTA BANDUNG",
        "NOMOR UJI : 12345/KIR/2025",
        "NO. POLISI : D 9876 ABC",
        "NOMOR RANGKA : MHKE9XYZ00112233",
        "NOMOR MESIN : 2ZR-1234567",
        "TGL UJI : 07/08/2025",
        "MASA BERLAKU : 07/08/2026",
    ]
    ctx = ParserContext(raw_lines=lines, debug=False)
    res = KIRExtractor().parse(ctx)
    fields = res.get("fields", {})

    assert fields.get("tgl_uji", {}).get("value") == "07-08-2025"
    assert fields.get("masa_berlaku", {}).get("value") == "07-08-2026"
    assert fields.get("nomor_rangka", {}).get("value").startswith("MHK")
    assert fields.get("nomor_mesin", {}).get("value").startswith("2ZR")
