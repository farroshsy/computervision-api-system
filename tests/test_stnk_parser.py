from app.models.schemas import ParserContext
from app.parser.stnk_parser.stnk_extractor import STNKExtractor


def test_stnk_parser_basic_fields():
    lines = [
        "SURAT TANDA NOMOR KENDARAAN BERMOTOR",
        "NAMA PEMILIK : PT. MAJU JAYA",
        "ALAMAT : JL. RAYA INDUSTRI NO. 5 BEKASI",
        "NO. POLISI : B 1234 XYZ",
        "NOMOR RANGKA : MHKE1ABCD12345678",
        "NOMOR MESIN : 1NZ-9876543",
        "MASA BERLAKU: 15/12/2029",
    ]
    ctx = ParserContext(raw_lines=lines, debug=False)
    res = STNKExtractor().parse(ctx)
    fields = res.get("fields", {})

    assert fields.get("nomor_polisi", {}).get("value") == "B 1234 XYZ"
    assert fields.get("owner", {}).get("value") == "PT. MAJU JAYA"
    assert fields.get("alamat", {}).get("value").startswith("JL.")
    assert fields.get("nomor_rangka", {}).get("value").startswith("MHK")
    assert fields.get("nomor_mesin", {}).get("value").startswith("1NZ")
