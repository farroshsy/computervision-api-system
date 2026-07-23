"""Plate recovery: fill an EMPTY plate from a valid-region token in the raw
OCR when label-geometry pairing left it blank (plate printed far from its
label). Must never turn a safe MISS into a wrong plate."""
from app.parser.spec_fields import recover_plate_from_lines


def plate(fields):
    r = fields.get("nomor_polisi")
    return r.get("value") if isinstance(r, dict) else r


def test_recovers_dashed_plate():
    # STNK_standard3: plate at the top of the card, label far below
    out = recover_plate_from_lines(["AD-9468-BV", "NOMOR REGISTRASI"], {})
    assert plate(out) == "AD 9468 BV"
    assert out["nomor_polisi"]["provenance"]["method"] == "plate_scan"


def test_recovers_colon_prefixed_plate():
    out = recover_plate_from_lines([":B 9437 SRU", "KEPOLISIAN"], {})
    assert plate(out) == "B 9437 SRU"


def test_rejects_two_digit_noise_off_bad_photo():
    # 'B 00 W' passes shape+region but is OCR noise — scan demands 4 digits
    assert plate(recover_plate_from_lines(["B 00 W", "garbled"], {})) is None


def test_rejects_invalid_region_code():
    # 'KA 2011' — KA is no Indonesian plate region
    assert plate(recover_plate_from_lines(["KA 2011"], {})) is None


def test_does_not_override_existing_valid_plate():
    out = recover_plate_from_lines(["B 1234 XY"], {"nomor_polisi": {"value": "AD 9468 BV"}})
    assert plate(out) == "AD 9468 BV"


def test_ambiguous_two_distinct_plates_skips():
    # two different valid 4-digit plates on the page -> can't choose -> review
    assert plate(recover_plate_from_lines(["AD 9468 BV", "B 9437 SRU"], {})) is None


def test_same_plate_twice_still_recovers():
    # multi-doc (STNK + tax receipt) prints the SAME plate twice -> one distinct
    out = recover_plate_from_lines([":B 9437 SRU", "B 9437 SRU"], {})
    assert plate(out) == "B 9437 SRU"


def test_type_code_slice_not_recovered():
    # 'S 401 RV' sliced from the type code 'S401RV-BMRLJJHF' is not a plate
    assert plate(recover_plate_from_lines(["S401RV-BMRLJJHF BVAN"], {})) is None
