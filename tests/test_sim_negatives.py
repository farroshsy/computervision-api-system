import pytest

from app.parser.sim_parser.sim_extractor import SIMExtractor
from app.models.schemas import ParserContext


def test_sim_number_requires_sim_cue():
    ext = SIMExtractor()
    # A long digit sequence appears but no 'SIM' cue; should abstain from sim_number
    lines = [
        "NAMA: ANDI",
        "ALAMAT: JL. SUDIRMAN",
        "12345678901234",
        "BERLAKU S/D 01-01-2030",
    ]
    ctx = ParserContext(raw_lines=lines, debug=False)
    res = ext.parse(ctx)
    f = res["fields"]
    assert "sim_number" not in f
