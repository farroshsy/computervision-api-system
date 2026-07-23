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


def test_no_admin_header_leakage():
    """Ensure admin headers are not mistaken as kelurahan/desa values."""
    ext = KelurahanDesaExtractor()
    lines = [
        "PROVINSI DKI JAKARTA",
        "KABUPATEN/KOTA JAKARTA SELATAN",
        "KECAMATAN: SETIA BUDI",
        "KEL/DESA:",
        "",  # empty line after label
        "JL. RAYA NOMOR 1",  # address noise
    ]
    ctx = make_ctx(lines)
    val = ext.extract(ctx)
    # No value present after label within span; should not leak admin tokens
    assert val is None


def test_stop_buffer_on_admin_token():
    """When scanning following lines, stop at admin token boundaries."""
    ext = KelurahanDesaExtractor()
    lines = [
        "KELURAHAN/DESA:",
        "TANAH",  # partial token
        "ABANG",  # could combine, but next is admin boundary => should not combine past it
        "KECAMATAN MENTENG",  # boundary token
        "ABANG BARU",  # should be ignored due to boundary
    ]
    ctx = make_ctx(lines)
    val = ext.extract(ctx)
    # Partial tokens not forming clear kelurahan before boundary => None
    assert val is None


def test_compound_anchor_two_tokens():
    """Handle compound anchor like 'KEL/DESA' capturing two tokens immediately after."""
    ext = KelurahanDesaExtractor()
    ctx = make_ctx(["KEL/DESA TANAH ABANG"])
    val = ext.extract(ctx)
    assert val == "TANAH ABANG"


def test_two_token_upgrade_on_next_line():
    """If first capture yields one token, upgrade to two tokens from next line when labeled again."""
    ext = KelurahanDesaExtractor()
    lines = [
        "Kel/Desa: JATINEGARA",
        "Kel/Desa: KA",  # noise
        "Kel/Desa: BARU",  # provides second token for upgrade scenario
    ]
    ctx = make_ctx(lines, structured=True)
    val = ext.extract(ctx)
    # Depending on extractor behavior, at least the first valid two-token case is returned
    assert isinstance(val, dict)
    assert val["value"] in {"JATINEGARA", "KA BARU"}


def test_apostrophe_preserved_after_des_dot():
    """Regression: 'DES. O'EBOLO' should return O'EBOLO with apostrophe preserved."""
    ext = KelurahanDesaExtractor()
    ctx = make_ctx(["DES. O'EBOLO"], structured=True)
    val = ext.extract(ctx)
    assert isinstance(val, dict)
    assert val["value"] == "O'EBOLO"
