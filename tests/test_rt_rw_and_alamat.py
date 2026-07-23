from app.models.schemas import ParserContext
from app.parser.ktp_parser.rt_rw_extractor import RtRwExtractor
from app.parser.ktp_parser.alamat_extractor import AlamatExtractor

def make_ctx(lines):
    return ParserContext(raw_lines=lines, debug=True)


def test_rt_rw_normalizes_padding():
    ctx = make_ctx([
        "RT/RW: 1/2"
    ])
    extr = RtRwExtractor()
    val = extr.extract(ctx)
    assert val == "001/002"


def test_rt_rw_from_next_line_after_label():
    ctx = make_ctx([
        "RT RW:",
        "003/45"
    ])
    extr = RtRwExtractor()
    val = extr.extract(ctx)
    assert val == "003/045"


def test_alamat_noisy_label_ALAMA7():
    ctx = make_ctx([
        "ALAMA7: JL. CONTOH NO. 123"
    ])
    extr = AlamatExtractor()
    val = extr.extract(ctx)
    assert isinstance(val, (str, dict))
    text = val if isinstance(val, str) else val.get('value')
    assert text and 'JL' in text.upper()


def test_alamat_suppress_bare_rt_rw_block():
    ctx = make_ctx([
        "ALAMAT:",
        "RT/RW"
    ])
    extr = AlamatExtractor()
    val = extr.extract(ctx)
    # Should not return just "RT/RW"
    assert val is None
