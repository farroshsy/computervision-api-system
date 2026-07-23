import pytest

from app.parser.ktp_parser.kelurahan_desa_extractor import KelurahanDesaExtractor
from app.models.schemas import ParserContext


def make_ctx(lines, structured=False):
    return ParserContext(
        raw_lines=lines,
        extracted_fields={},
        debug=False,
        strict_admin_filter=True,
        enforce_vowel_check=False,
        allow_standalone_address=True,
        allow_standalone_kelurahan=True,
        structured_output=structured,
    )


def test_kel_dot_variant():
    ext = KelurahanDesaExtractor()
    ctx = make_ctx(["KEL. Tanah Abang"])
    val = ext.extract(ctx)
    assert isinstance(val, str)
    assert val == "TANAH ABANG"


def test_des_dot_variant_with_apostrophe():
    ext = KelurahanDesaExtractor()
    ctx = make_ctx(["DES. O'EBOLO"], structured=True)
    val = ext.extract(ctx)
    assert isinstance(val, dict)
    assert val['value'] == "O'EBOLO"
    assert 0.0 <= float(val['confidence']) <= 1.0
