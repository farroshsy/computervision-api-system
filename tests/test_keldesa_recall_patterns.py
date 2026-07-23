import pytest

from app.parser.ktp_parser.kelurahan_desa_extractor import KelurahanDesaExtractor
from app.models.schemas import ParserContext


def make_ctx(lines, structured=False):
    # Minimal ParserContext usage for extractor tests
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


def test_label_variants_space_and_slash_same_line():
    ext = KelurahanDesaExtractor()
    # "KEL DESA" with space
    ctx1 = make_ctx(["Kel Desa Tanah Abang"])  # mixed case
    val1 = ext.extract(ctx1)
    assert isinstance(val1, str)
    assert val1 == "TANAH ABANG"

    # "KEL/DESA" with slash
    ctx2 = make_ctx(["KEL/DESA Jatinegara"])  # mixed case
    val2 = ext.extract(ctx2)
    assert val2 == "JATINEGARA"


def test_label_on_one_line_value_on_following_lines_within_3():
    ext = KelurahanDesaExtractor()
    lines = [
        "Alamat: JL. ABC NO 1",
        "Kelurahan/Desa:",  # label on its own line
        "",
        "Tanah Abang",  # within +2 lines
    ]
    ctx = make_ctx(lines)
    val = ext.extract(ctx)
    assert val == "TANAH ABANG"


def test_hyphen_and_apostrophe_preserved():
    ext = KelurahanDesaExtractor()
    # Hyphenated name
    ctx1 = make_ctx(["KELURAHAN Bala-Bala"])  # should keep hyphen
    val1 = ext.extract(ctx1)
    assert val1 == "BALA-BALA"

    # Apostrophe name
    ctx2 = make_ctx(["DESA O'ebolo"])  # should keep apostrophe
    val2 = ext.extract(ctx2)
    assert val2 == "O'EBOLO"
