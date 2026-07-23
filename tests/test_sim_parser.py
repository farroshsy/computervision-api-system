from app.models.schemas import ParserContext
from app.parser.sim_parser.sim_extractor import SIMExtractor


def test_sim_parser_basic_fields():
    lines = [
        "REPUBLIK INDONESIA",
        "SURAT IZIN MENGEMUDI",
        "SIM C",
        "NAMA / NAME : JOHN DOE",
        "ALAMAT / ADDRESS : JL. MERDEKA NO. 1 JAKARTA",
        "NO: 3276010203040506",
        "BERLAKU S/D 12-08-2030",
    ]
    ctx = ParserContext(raw_lines=lines, debug=False)
    res = SIMExtractor().parse(ctx)
    fields = res.get("fields", {})

    assert fields.get("id_number", {}).get("value") == "3276010203040506"
    assert fields.get("name", {}).get("value") == "JOHN DOE"
    assert fields.get("address", {}).get("value").startswith("JL.")
    assert fields.get("expiry_date", {}).get("value") == "12-08-2030"
