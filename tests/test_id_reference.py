"""Tests for Indonesian reference-data lexicon correction and NIK cross-checks."""
from app.utils.id_reference import (
    fuzzy_correct,
    fuzzy_correct_fields,
    nik_structure_info,
    nik_cross_check,
    AGAMA,
    PROVINCES,
)


def test_fuzzy_correct_ocr_noise():
    assert fuzzy_correct("ISLAN", AGAMA) == "ISLAM"
    assert fuzzy_correct("KHONG HUCU", AGAMA) == "KHONGHUCU"
    assert fuzzy_correct("JAWA T1MUR".replace("1", "I"), PROVINCES) == "JAWA TIMUR"
    assert fuzzy_correct("SUMATERA UTARA", PROVINCES) == "SUMATERA UTARA"


def test_fuzzy_correct_rejects_garbage():
    assert fuzzy_correct("XYZQW", AGAMA) is None
    assert fuzzy_correct("", AGAMA) is None
    assert fuzzy_correct(None, AGAMA) is None


def test_fuzzy_correct_fields_in_place():
    fields = {
        "agama": {"value": "ISLAN", "confidence": 0.8},
        "jenis_kelamin": {"value": "LAKI LAKI", "confidence": 0.7},
        "status_perkawinan": {"value": "KAW1N".replace("1", "I"), "confidence": 0.9},
        "nama": {"value": "PUDIN", "confidence": 0.9},  # open vocab — untouched
    }
    out = fuzzy_correct_fields(fields)
    assert out["agama"]["value"] == "ISLAM"
    assert out["agama"]["provenance"]["lexicon_corrected_from"] == "ISLAN"
    assert out["jenis_kelamin"]["value"] == "LAKI-LAKI"
    assert out["status_perkawinan"]["value"] == "KAWIN"
    assert out["nama"]["value"] == "PUDIN"


def test_nik_structure_info_decodes():
    # Real-format NIK: Banten (36), male, born 10-01-1990 (from sample KTP)
    info = nik_structure_info("3602171001900004")
    assert info["province_code"] == "36"
    assert info["province_name"] == "BANTEN"
    assert (info["dob_dd"], info["dob_mm"], info["dob_yy"]) == (10, 1, 90)
    assert info["is_female"] is False


def test_nik_structure_female_plus40():
    info = nik_structure_info("3175095801131001")
    assert info["is_female"] is True
    assert info["dob_dd"] == 18


def test_nik_cross_check_consistent():
    fields = {
        "nik": {"value": "3602171001900004"},
        "tanggal_lahir": {"value": "10-01-1990"},
        "jenis_kelamin": {"value": "LAKI-LAKI"},
    }
    assert nik_cross_check(fields) == []


def test_nik_cross_check_dob_mismatch():
    fields = {
        "nik": {"value": "3602171001900004"},
        "tanggal_lahir": {"value": "18-04-1993"},
    }
    assert "nik_dob_mismatch" in nik_cross_check(fields)


def test_nik_cross_check_gender_mismatch():
    fields = {
        "nik": {"value": "3602171001900004"},  # male encoding
        "jenis_kelamin": {"value": "PEREMPUAN"},
    }
    assert "nik_gender_mismatch" in nik_cross_check(fields)


def test_nik_cross_check_unknown_region():
    fields = {"nik": {"value": "9902171001900004"}}  # 99 = no such province
    assert "nik_region_code_unknown" in nik_cross_check(fields)


def test_nik_cross_check_absent_fields_silent():
    assert nik_cross_check({}) == []
    assert nik_cross_check({"nik": {"value": "123"}}) == []


def test_regions_gazetteer_loaded():
    from app.utils.id_reference import _load_regions, kabupaten_names

    provinces, kabupaten = _load_regions()
    assert len(kabupaten) == 514
    # 2025 Kepmendagri data: 38 provinces incl. the four new Papua ones
    assert len(provinces) == 38
    assert provinces["96"] == "PAPUA BARAT DAYA"
    assert kabupaten["3602"] == "KABUPATEN LEBAK"
    names = kabupaten_names()
    assert "LEBAK" in names
    assert "JAKARTA PUSAT" in names  # KOTA ADMINISTRASI prefix stripped
    # Prefix words stripped, but names like KOTABARU/KOTAWARINGIN (no space
    # after KOTA) must stay whole
    assert not any(n.startswith(("KABUPATEN ", "KAB. ", "KOTA ")) for n in names)
    assert "KOTABARU" in names


def test_nik_kabupaten_validation():
    # 3602 = Kab. Lebak (valid); 3699 = no such kabupaten in Banten
    info = nik_structure_info("3602171001900004")
    assert info["kabupaten_name"] == "KABUPATEN LEBAK"
    reasons = nik_cross_check({"nik": {"value": "3699171001900004"}})
    assert "nik_kabupaten_code_unknown" in reasons
    assert "nik_region_code_unknown" not in reasons


def test_ktp_extract_then_correct_chain():
    """E2E: noisy OCR values survive extraction and get lexicon-corrected."""
    from app.parser.ktp_parser.ktp_parser import parse_ktp_fields

    fields = parse_ktp_fields([
        "PROVINSI BANTEN",
        "NIK : 3602171001900004",
        "Nama : PUDIN",
        "Tempat/Tgl Lahir : LEBAX, 10-01-1990",
        "Jenis kelamin : LAKI-LAKI",
        "Agama : ISLAN",
        "Kewarganegaraan: WNl",
    ])

    def val(k):
        v = fields.get(k)
        return v.get("value") if isinstance(v, dict) else v

    assert val("agama") == "ISLAM"          # fuzzy fallback in extractor
    assert val("kewarganegaraan") == "WNI"  # WN? confusion pattern
    assert val("tanggal_lahir") == "1990-01-10"  # label with space now matches
    # tempat_lahir: date stripped pre-folding; LEBAX later corrected by gazetteer
    out = fuzzy_correct_fields(dict(fields))
    tl = out.get("tempat_lahir")
    assert (tl.get("value") if isinstance(tl, dict) else tl) == "LEBAK"


def test_gender_not_inferred_from_p_word():
    """PROVINSI... must not become PEREMPUAN via startswith('P')."""
    from app.parser.ktp_parser.jenis_kelamin_extractor import JenisKelaminExtractor
    from app.models.schemas import ParserContext

    ext = JenisKelaminExtractor()
    ctx = ParserContext(raw_lines=["PROVINSI BANTEN", "PEKALONGAN KOTA"], debug=False)
    assert ext.extract(ctx) is None
    ctx2 = ParserContext(raw_lines=["Jenis Kelamin : P"], debug=False)
    assert ext.extract(ctx2) == "PEREMPUAN"


def test_tempat_lahir_gazetteer_correction():
    fields = {"tempat_lahir": {"value": "LEBAX", "confidence": 0.6}}
    out = fuzzy_correct_fields(fields)
    assert out["tempat_lahir"]["value"] == "LEBAK"
    # Foreign / unknown city stays untouched (correct, never reject)
    fields2 = {"tempat_lahir": {"value": "KUALA LUMPUR", "confidence": 0.9}}
    out2 = fuzzy_correct_fields(fields2)
    assert out2["tempat_lahir"]["value"] == "KUALA LUMPUR"


def test_brand_lexicon_corrects_ocr_slips():
    from app.utils.id_reference import fuzzy_correct_fields
    fields = fuzzy_correct_fields({"brand": "USUZU"})
    assert fields["brand"]["value"] == "ISUZU"
    fields = fuzzy_correct_fields({"brand": {"value": "DATHATSU", "confidence": 0.8}})
    assert fields["brand"]["value"] == "DAIHATSU"
    # a correct brand passes through untouched
    fields = fuzzy_correct_fields({"brand": "HINO"})
    assert (fields["brand"]["value"] if isinstance(fields["brand"], dict) else fields["brand"]) == "HINO"


def test_kecamatan_gazetteer_loaded_and_corrects():
    from app.utils.id_reference import kecamatan_names, fuzzy_correct_fields
    names = kecamatan_names()
    # 7,285 kecamatan codes -> ~6.9k unique names (same name recurs across provinces)
    assert len(names) > 6500
    assert "BAKONGAN" in names
    fields = fuzzy_correct_fields({"kecamatan": "BAKONCAN"})
    assert fields["kecamatan"]["value"] == "BAKONGAN"


def test_dob_derived_from_nik_when_missing():
    from app.utils.id_reference import derive_dob_from_nik
    # NIK dob segment: dd=17 mm=08 yy=90 (male) -> 17-08-1990
    fields = derive_dob_from_nik({"nik": "3174041708900001"})
    assert fields["tanggal_lahir"]["value"] == "17-08-1990"
    assert fields["tanggal_lahir"]["provenance"]["method"] == "derived_from_nik"
    # female +40 convention: dd=57 -> 17
    fields = derive_dob_from_nik({"nik": "3174045708900001"})
    assert fields["tanggal_lahir"]["value"] == "17-08-1990"


def test_dob_not_derived_over_readable_printed_date():
    from app.utils.id_reference import derive_dob_from_nik
    fields = derive_dob_from_nik({
        "nik": "3174041708900001",
        "tanggal_lahir": {"value": "18-08-1990"},
    })
    # printed date is readable -> kept, even though it disagrees (advisory
    # nik_dob_mismatch handles the disagreement)
    assert fields["tanggal_lahir"]["value"] == "18-08-1990"


def test_dob_not_invented_from_impossible_nik_segment():
    from app.utils.id_reference import derive_dob_from_nik
    # mm=13 is not a month -> misread NIK, no derivation
    fields = derive_dob_from_nik({"nik": "3174041713900001"})
    assert "tanggal_lahir" not in fields


def test_tempat_lahir_prefix_rescue():
    from app.utils.id_reference import fuzzy_correct_fields
    # trailing garbage = misread birthdate glued onto the city
    fields = fuzzy_correct_fields({"tempat_lahir": "GARUT I -OS-I S"})
    assert fields["tempat_lahir"]["value"] == "GARUT"
    # no city prefix -> untouched, never invented
    fields = fuzzy_correct_fields({"tempat_lahir": "LAKI-LAI"})
    raw = fields["tempat_lahir"]
    assert (raw["value"] if isinstance(raw, dict) else raw) == "LAKI-LAI"


def test_nik_repaired_when_date_segment_impossible():
    from app.utils.id_reference import repair_nik_from_printed_dob
    # digits 9-10 read '27' as the month — month 27 does not exist
    fields = repair_nik_from_printed_dob({
        "nik": {"value": "3276052927940002"},
        "tanggal_lahir": {"value": "29-07-1994"},
    })
    assert fields["nik"]["value"] == "3276052907940002"
    assert fields["nik"]["provenance"]["nik_repaired_from_dob"] == "3276052927940002"


def test_nik_with_valid_segment_never_touched():
    from app.utils.id_reference import repair_nik_from_printed_dob
    # yy disagrees with printed but the segment IS a valid date -> ambiguous, keep
    fields = repair_nik_from_printed_dob({
        "nik": "3313012705770008",
        "tanggal_lahir": {"value": "27-05-1979"},
    })
    assert fields["nik"] == "3313012705770008"


def test_nik_repair_preserves_female_offset():
    from app.utils.id_reference import repair_nik_from_printed_dob
    # dd=69 (29+40, female) with impossible month 27 -> repaired keeps +40
    fields = repair_nik_from_printed_dob({
        "nik": "3276056927940002",
        "tanggal_lahir": {"value": "29-07-1994"},
    })
    assert fields["nik"] == "3276056907940002"
