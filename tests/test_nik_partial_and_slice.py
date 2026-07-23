import re
from app.models.schemas import ParserContext
from app.parser.ktp_parser.nik_extractor import NikExtractor


def make_ctx(lines):
    return ParserContext(raw_lines=lines, debug=True)


def test_nik_records_partial_when_15_digits():
    # "NTK3 31730607048000G" -> after substitutions, G->6 gives 15 digits
    lines = ["NTK3 31730607048000G"]
    ctx = make_ctx(lines)
    extr = NikExtractor()
    nik = extr.extract(ctx)
    assert nik is None
    # partial_nik should be recorded
    assert 'partial_nik' in ctx.fields
    val = ctx.fields['partial_nik']['value']
    assert isinstance(val, str)
    assert re.fullmatch(r"\d{14,15}", val)


def test_nik_17_to_16_slicing_returns_16_digits():
    # 17-digit blob
    lines = ["NIK 23313012205790008"]
    ctx = make_ctx(lines)
    extr = NikExtractor()
    nik = extr.extract(ctx)
    assert nik is not None
    assert nik.isdigit() and len(nik) == 16
    # Ensure it's from either first or last 16 slice
    blob = re.sub(r"\D", "", lines[0])
    candidates = {blob[:16], blob[1:17]}
    assert nik in candidates
