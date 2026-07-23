"""Spatial label->value pairing on synthetic OCR line geometry."""
from app.parser.spatial_pairing import (
    _label_score,
    _value_below,
    _value_right_of,
    pair_fields_spatially,
)


def item(text, x0, x1, cy, h=20.0, conf=0.9):
    return {"text": text, "conf": conf, "x0": x0, "x1": x1, "cy": cy, "h": h}


class TestLabelScore:
    def test_exact_label(self):
        assert _label_score("NOMOR RANGKA", "NOMOR RANGKA") == 1.0

    def test_glued_label_contains(self):
        # PaddleOCR often glues label + colon + garbage into one box
        assert _label_score("NOMORRANGKA:", "NOMOR RANGKA") == 1.0

    def test_garbled_label_fuzzy(self):
        assert _label_score("N0MOR RANGK4 KENDARAAN", "NOMOR RANGKA KENDARAAN") > 0.62

    def test_unrelated_text_scores_low(self):
        assert _label_score("MHKA123456789", "NOMOR RANGKA") < 0.5


class TestGeometry:
    def test_value_right_of_same_row(self):
        label = item("NOMOR RANGKA", 10, 150, 100)
        value = item("MHKV1BA3JEK123456", 170, 400, 102)
        other_row = item("NOMOR MESIN", 10, 140, 140)
        assert _value_right_of([label, value, other_row], label) == "MHKV1BA3JEK123456"

    def test_right_of_concatenates_in_x_order(self):
        label = item("MASA BERLAKU", 10, 150, 100)
        a = item("12", 160, 180, 101)
        b = item("MEI 2026", 190, 260, 99)
        assert _value_right_of([label, b, a], label) == "12 MEI 2026"

    def test_value_below_when_row_empty(self):
        label = item("NAMA PEMILIK", 10, 150, 100)
        below = item("BUDI SANTOSO", 12, 160, 128)
        far_below = item("JL MERDEKA 1", 12, 160, 200)
        assert _value_below([label, below, far_below], label) == "BUDI SANTOSO"


class TestPairing:
    def test_fills_missing_field(self):
        items = [
            item("NOMOR RANGKA", 10, 150, 100),
            item("MHKV1BA3JEK123456", 170, 400, 101),
        ]
        fields = pair_fields_spatially("STNK", items, {})
        assert fields["nomor_rangka"]["value"] == "MHKV1BA3JEK123456"
        assert fields["nomor_rangka"]["provenance"]["method"] == "spatial_pairing"

    def test_replaces_pattern_invalid_value(self):
        # rule path captured label text as the value — shape-invalid, replace
        items = [
            item("NOMOR RANGKA", 10, 150, 100),
            item("MHKV1BA3JEK123456", 170, 400, 101),
        ]
        fields = {"nomor_rangka": {"value": "NIK/VIN", "confidence": 0.8}}
        out = pair_fields_spatially("STNK", items, fields)
        assert out["nomor_rangka"]["value"] == "MHKV1BA3JEK123456"

    def test_keeps_pattern_valid_value(self):
        items = [
            item("NOMOR RANGKA", 10, 150, 100),
            item("MHKV1BA3JEK123456", 170, 400, 101),
        ]
        fields = {"nomor_rangka": {"value": "JTFB71GK5K0012345", "confidence": 0.9}}
        out = pair_fields_spatially("STNK", items, fields)
        assert out["nomor_rangka"]["value"] == "JTFB71GK5K0012345"

    def test_kir_valid_until_date(self):
        items = [
            item("MASA BERLAKU UJI BERKALA", 10, 250, 300),
            item(": 17 NOVEMBER 2025", 260, 450, 301),
        ]
        fields = pair_fields_spatially("KIR", items, {})
        assert "17" in fields["valid_until"]["value"]
        assert "2025" in fields["valid_until"]["value"]

    def test_plate_pattern_extracted_from_row_text(self):
        items = [
            item("NOMOR REGISTRASI", 10, 180, 50),
            item(": B 9034 UEH", 190, 320, 51),
        ]
        fields = pair_fields_spatially("STNK", items, {})
        assert fields["nomor_polisi"]["value"].replace(" ", "") == "B9034UEH"

    def test_column_gap_stops_row_sweep(self):
        # two-column STNK: watermark far right of the value must not be glued on
        items = [
            item("NAMA PEMILIK", 38, 137, 438, h=17),
            item("KURNIANINGRUM", 179, 355, 440, h=19),
            item("STNK", 819, 927, 446, h=36),
        ]
        fields = pair_fields_spatially("STNK", items, {})
        assert fields["owner"]["value"] == "KURNIANINGRUM"

    def test_empty_boxes_ignored(self):
        items = [
            item("NAMA PEMILIK", 38, 137, 438, h=17),
            item("BUDI SANTOSO", 179, 355, 440, h=19),
            item("", 360, 500, 441, h=20),
        ]
        fields = pair_fields_spatially("STNK", items, {})
        assert fields["owner"]["value"] == "BUDI SANTOSO"

    def test_runner_up_label_used_when_best_row_empty(self):
        # garbled plate label ties the mesin label; its row has no value —
        # the true (garbled) mesin label must still get paired
        items = [
            item("NOMOROLISI", 10, 120, 50, h=15),          # nothing to its right
            item("NONDE MESIN", 19, 104, 638, h=17),
            item("4K.3HH09391", 157, 279, 636, h=20),
        ]
        fields = pair_fields_spatially("STNK", items, {})
        assert fields["nomor_mesin"]["value"] == "4K3HH09391"

    def test_mesin_separators_stripped(self):
        items = [
            item("NOMOR MESIN", 10, 120, 50),
            item("4K.3HH 09391", 130, 300, 51),
        ]
        fields = pair_fields_spatially("STNK", items, {})
        assert fields["nomor_mesin"]["value"] == "4K3HH09391"

    def test_vin_o_i_q_corrected_and_label_residue_stripped(self):
        # ISO 3779: VINs never contain I/O/Q — OCR 'O' in a 17-char VIN is '0';
        # glued 'NIKVIN :' residue before the token must not join it
        items = [
            item("NOMOR RANGKA", 10, 150, 100),
            item("NIKVIN : MHYHDC61TNJ25OO26", 160, 500, 101),
        ]
        fields = pair_fields_spatially("STNK", items, {"nomor_rangka": "NIKVIN : MHYHDC61TNJ25OO26"})
        got = fields["nomor_rangka"]
        assert (got["value"] if isinstance(got, dict) else got) == "MHYHDC61TNJ250026"

    def test_rule_value_rescued_before_geometry(self):
        # rule path glued label residue to the RIGHT token; geometry points
        # at a watermark — the rescue must win, the watermark must not
        items = [
            item("NOMOR RANGKA/NIK/VIN", 10, 170, 616, h=24),
            item("VEHICLE OWNERSHIP DOC", 180, 420, 615, h=20),
        ]
        fields = pair_fields_spatially(
            "STNK", items, {"nomor_rangka": {"value": "NIKVIN : MHYHDC61TNJ25OO26"}})
        assert fields["nomor_rangka"]["value"] == "MHYHDC61TNJ250026"

    def test_despaced_english_words_never_pass_as_vin(self):
        # "VEHICLEOWNERSHIPDOC" is 17+ letters; without real digits it is
        # not a VIN, even after I/O->1/0 mapping would fake some
        items = [
            item("NOMOR RANGKA", 10, 150, 100),
            item("VEHICLE OWNERSHIP DOC", 160, 500, 101),
        ]
        fields = pair_fields_spatially("STNK", items, {})
        assert "nomor_rangka" not in fields

    def test_rangka_duplicate_evicted_from_cert_and_mesin(self):
        # rule path leaked the VIN into certificate/engine slots; spatial
        # refills certificate from its own label row
        items = [
            item("NOMOR UJI", 10, 120, 100),
            item("TBN5380", 130, 250, 101),
        ]
        fields = pair_fields_spatially("KIR", items, {
            "nomor_rangka": {"value": "FT418V550967"},
            "certificate_number": {"value": "FT418V550967"},
            "nomor_mesin": {"value": "FT418V550967"},
        })
        assert fields["certificate_number"]["value"] == "TBN5380"
        assert "nomor_mesin" not in fields
        assert fields["nomor_rangka"]["value"] == "FT418V550967"

    def test_kelas_jalan_roman_numeral(self):
        items = [
            item("KELAS JALAN", 10, 120, 100),
            item(": III", 130, 180, 101),
        ]
        fields = pair_fields_spatially("KIR", items, {})
        assert fields["kelas_jalan"]["value"] == "III"

    def test_certificate_thirteen_chars_not_truncated(self):
        items = [
            item("NOMOR UJI KENDARAAN", 10, 200, 100),
            item("BE02C20011234", 210, 400, 101),
        ]
        fields = pair_fields_spatially("KIR", items, {})
        assert fields["certificate_number"]["value"] == "BE02C20011234"

    def test_jbb_canonicalized_to_digits(self):
        # rule path emitted display form; API canonical form is digits
        items = [item("ANY TEXT", 0, 50, 10)]
        fields = pair_fields_spatially("KIR", items, {"jbb_kg": {"value": "8,000 KG"}})
        assert fields["jbb_kg"]["value"] == "8000"

    def test_owner_garbage_replaced_by_name(self):
        # rule path captured the plate as the owner — not a plausible name
        items = [
            item("NAMA PEMILIK", 38, 137, 438),
            item("TRI LESTARI DIAN MAS PT", 179, 420, 440),
        ]
        fields = pair_fields_spatially("STNK", items, {"owner": "AB-8168-BK"})
        assert fields["owner"]["value"] == "TRI LESTARI DIAN MAS PT"

    def test_label_text_never_survives_as_certificate(self):
        items = [
            item("NOMOR UJI KENDARAAN", 10, 200, 100),
            item("CB71C250659", 210, 400, 101),
        ]
        fields = pair_fields_spatially("KIR", items, {"certificate_number": "Engine number"})
        assert fields["certificate_number"]["value"] == "CB71C250659"

    def test_plate_that_is_vin_prefix_dropped(self):
        # a 'plate' reading inside the VIN is the VIN misread as a plate
        items = [
            item("NOMOR REGISTRASI KENDARAAN", 10, 250, 100),
            item("FT418V550967", 260, 460, 101),
            item("NOMOR RANGKA KENDARAAN", 10, 250, 140),
            item("FT418V550967", 260, 460, 141),
        ]
        fields = pair_fields_spatially("KIR", items, {})
        assert fields["nomor_rangka"]["value"] == "FT418V550967"
        assert "vehicle_id" not in fields

    def test_spreadsheet_epoch_date_replaced(self):
        # "30-12-1899" is a spreadsheet-epoch artifact, not a validity date
        items = [
            item("MASA BERLAKU UJI BERKALA", 10, 250, 100),
            item(": 26-07-2023", 260, 400, 101),
        ]
        fields = pair_fields_spatially("KIR", items, {"valid_until": {"value": "30-12-1899"}})
        assert fields["valid_until"]["value"] == "2023-07-26"

    def test_same_date_different_format_untouched(self):
        # geometry-wins replaces only when the label-row date DIFFERS;
        # the same date in another format is not a disagreement
        items = [
            item("MASA BERLAKU UJI BERKALA", 10, 250, 100),
            item(": 26-07-2023", 260, 400, 101),
        ]
        fields = pair_fields_spatially("KIR", items, {"valid_until": {"value": "26-07-2023"}})
        assert fields["valid_until"]["value"] == "26-07-2023"

    def test_implausible_year_not_extracted(self):
        items = [
            item("MASA BERLAKU UJI BERKALA", 10, 250, 100),
            item(": 30-12-1899", 260, 400, 101),
        ]
        fields = pair_fields_spatially("KIR", items, {})
        assert "valid_until" not in fields

    def test_ktp_nik_from_glued_label_box(self):
        # whole row read as one box: value lives INSIDE the label box
        items = [item("NIK : 3174041708900001", 10, 400, 100)]
        fields = pair_fields_spatially("KTP", items, {})
        assert fields["nik"]["value"] == "3174041708900001"

    def test_ktp_combined_birth_row_splits(self):
        items = [
            item("Tempat/Tgl Lahir", 10, 150, 100),
            item(": JAKARTA, 17-08-1990", 160, 420, 101),
        ]
        fields = pair_fields_spatially("KTP", items, {})
        assert fields["tempat_lahir"]["value"] == "JAKARTA"
        assert fields["tanggal_lahir"]["value"] == "17-08-1990"

    def test_ktp_gender_cut_at_blood_type(self):
        items = [
            item("Jenis Kelamin", 10, 130, 100),
            item(": LAKI-LAKI", 140, 260, 101),
            item("Gol. Darah : O", 300, 420, 100),
        ]
        fields = pair_fields_spatially("KTP", items, {})
        assert fields["jenis_kelamin"]["value"] == "LAKI-LAKI"

    def test_short_label_needs_exact_prefix(self):
        # ELEKTRONIK contains 'NIK' but is not the NIK label
        items = [
            item("KARTU TANDA PENDUDUK ELEKTRONIK", 10, 400, 50),
            item("3174041708900001", 10, 300, 100),
        ]
        fields = pair_fields_spatially("KTP", items, {})
        assert "nik" not in fields

    def test_ktp_fills_missing_only(self):
        items = [
            item("Nama", 10, 60, 100),
            item(": BUDI SANTOSO", 70, 250, 101),
        ]
        fields = pair_fields_spatially("KTP", items, {"nama": {"value": "BUDI SANTOSA"}})
        # existing plausible name is kept even though geometry disagrees
        assert fields["nama"]["value"] == "BUDI SANTOSA"

    def test_no_labels_matched_is_noop(self):
        items = [item("RANDOM TEXT", 0, 100, 10), item("MORE NOISE", 0, 90, 40)]
        fields = {"owner": {"value": "BUDI"}}
        assert pair_fields_spatially("STNK", items, fields) == fields

    def test_unknown_doc_type_is_noop(self):
        assert pair_fields_spatially("SIM", [item("A", 0, 10, 5)], {"x": 1}) == {"x": 1}

    def test_empty_items_is_noop(self):
        assert pair_fields_spatially("STNK", [], {"x": 1}) == {"x": 1}


class TestCompletionUpgrade:
    def test_truncated_status_completed_from_row(self):
        # rule path kept only "KAWIN" from a row that prints "BELUM KAWIN"
        items = [item("Stalus Perkawinan: BELUM KAWIN", 13, 365, 360)]
        fields = pair_fields_spatially("KTP", items, {"status_perkawinan": "KAWIN"})
        assert fields["status_perkawinan"]["value"] == "BELUM KAWIN"

    def test_different_value_not_upgraded(self):
        # row disagrees but is not a completion -> existing kept
        items = [item("Status Perkawinan: CERAI HIDUP", 13, 365, 360)]
        fields = pair_fields_spatially("KTP", items, {"status_perkawinan": "KAWIN"})
        assert fields["status_perkawinan"] == "KAWIN"

    def test_single_word_vocab_never_upgraded(self):
        # agama values are single words; "ISLAM KAWIN" is the neighbouring
        # column glued on, not a fuller read
        items = [item("Agama : ISLAM KAWIN", 13, 400, 300)]
        fields = pair_fields_spatially("KTP", items, {"agama": "ISLAM"})
        assert fields["agama"] == "ISLAM"


class TestGoodSampleFixes:
    """Each fix here traces to a diagnosed miss on a real good sample."""

    def test_gender_value_not_a_plausible_place(self):
        # rule path put the gender line into tempat_lahir; the glued
        # birth row must replace it
        items = [item("Tempat/Tgi Lahir: PASURUAN, 05-12-1977", 36, 602, 238, h=18)]
        fields = pair_fields_spatially("KTP", items, {"tempat_lahir": "LAKI-LAI"})
        assert fields["tempat_lahir"]["value"] == "PASURUAN"

    def test_masa_berlaku_row_beats_wrong_rule_date(self):
        # KIR prints several dates; rule grabbed 18 APRIL 2025 from
        # elsewhere — the date on the MASA BERLAKU row wins
        items = [
            item("Masa berlaku uji", 403, 484, 772, h=16),
            item("berkala", 404, 441, 782, h=14),
            item(": 01 JANUARY 2026", 510, 608, 782, h=16),
        ]
        fields = pair_fields_spatially("KIR", items, {"valid_until": {"value": "18-04-2025"}})
        assert fields["valid_until"]["value"] == "2026-01-01"

    def test_english_month_normalized_iso(self):
        items = [
            item("MASA BERLAKU UJI BERKALA", 10, 250, 300),
            item(": 01 JANUARY 2026", 260, 450, 301),
        ]
        fields = pair_fields_spatially("KIR", items, {})
        assert fields["valid_until"]["value"] == "2026-01-01"

    def test_nama_recovered_from_nik_anchor(self):
        # the 'Nama' label box was not read at all; the colon box right
        # under the NIK row is the name — replaces a one-word fragment
        items = [
            item("NIK : 3514042505770001", 36, 500, 170, h=22),
            item(": AMIN TOHARI", 276, 477, 204, h=18),
        ]
        fields = pair_fields_spatially("KTP", items, {"nama": "SYAH"})
        assert fields["nama"]["value"] == "AMIN TOHARI"
        assert fields["nama"]["provenance"]["method"] == "nik_anchor"

    def test_nik_anchor_keeps_full_existing_name(self):
        items = [
            item("NIK : 3514042505770001", 36, 500, 170, h=22),
            item(": AMIN TOHARI", 276, 477, 204, h=18),
        ]
        fields = pair_fields_spatially("KTP", items, {"nama": "BUDI SANTOSO"})
        assert fields["nama"] == "BUDI SANTOSO"


class TestSimExpiryZone:
    def test_noop_when_expiry_present(self):
        from app.parser.sim_expiry_zone import recover_sim_expiry
        fields = {"expiry_date": {"value": "2024-07-01"}}
        out = recover_sim_expiry(b"junk", [item("1024", 0, 50, 100)], dict(fields))
        assert out["expiry_date"]["value"] == "2024-07-01"

    def test_noop_without_anchor(self):
        from app.parser.sim_expiry_zone import recover_sim_expiry
        # no digit fragments in the bottom half -> untouched, no decode attempt
        out = recover_sim_expiry(b"junk", [item("JAKA SALMAN", 0, 100, 900)], {})
        assert "expiry_date" not in out

    def test_anchor_selection(self):
        from app.parser.sim_expiry_zone import _digit_fragments
        items = [
            item("JAKA SALMAN", 0, 100, 100),
            item("01-07-2024", 0, 100, 850),   # full date -> not an anchor
            item("1024", 0, 50, 900),          # fragment -> anchor
            item("14278708000059", 0, 200, 880),  # too many digits
        ]
        anchors = _digit_fragments(items)
        assert len(anchors) == 1 and anchors[0]["text"] == "1024"


class TestForensicsRoundFixes:
    """Each fix traces to a row in the miss-forensics actionable list."""

    def test_jbb_label_row_beats_regulation_text(self):
        # rule path took "JBB<=3500kg" REGULATION text; the card's own
        # glued label row says 2950
        items = [item("JBB/JBKB: 2950 kg/0", 34, 179, 1213, h=16)]
        fields = pair_fields_spatially("KIR", items, {"jbb_kg": {"value": "3500"}})
        assert fields["jbb_kg"]["value"] == "2950"

    def test_kelas_longest_roman_wins(self):
        items = [
            item("Kelas jalan", 10, 120, 100),
            item(": I / III", 130, 260, 101),
        ]
        fields = pair_fields_spatially("KIR", items, {})
        assert fields["kelas_jalan"]["value"] == "III"

    def test_fill_loop_cannot_releak_vin_into_cert(self):
        # the cert label row CONTAINS the rangka on dense paper forms —
        # post-fill dedupe must evict it again (empty beats wrong)
        items = [
            item("Nomor uji kendaraan", 10, 200, 100),
            item("FT418V550967", 210, 400, 101),
        ]
        fields = pair_fields_spatially("KIR", items, {
            "nomor_rangka": {"value": "FT418V550967"},
            "certificate_number": {"value": "FT418V550967"},
        })
        assert "certificate_number" not in fields
        assert fields["nomor_rangka"]["value"] == "FT418V550967"

    def test_truncated_mesin_completed_from_page(self):
        # STNK repeats the engine number in the tax block, complete
        items = [
            item("NOMOR MESIN", 10, 120, 100),
            item("K15BT14440", 130, 280, 101),          # truncated read
            item("KODE NJKB K15BT1444012", 400, 700, 500),
        ]
        fields = pair_fields_spatially("STNK", items, {})
        assert fields["nomor_mesin"]["value"] == "K15BT1444012"

    def test_sim_standalone_class_box(self):
        items = [
            item("SURAT IZIN MENGEMUDI", 10, 400, 50),
            item("A", 579, 633, 100),
            item("JAKA SALMAN", 10, 200, 300),
            item("footer text", 10, 200, 400),
        ]
        fields = pair_fields_spatially("SIM", items, {})
        assert fields["class"]["value"] == "A"

    def test_sim_two_classes_ambiguous_skip(self):
        items = [
            item("A", 100, 130, 50),
            item("BII", 200, 260, 60),
            item("filler", 10, 200, 400),
        ]
        fields = pair_fields_spatially("SIM", items, {})
        assert "class" not in fields

    def test_sim_name_from_enumerated_row(self):
        # rule path misfiled the birth row as the name
        items = [item("1. ROHIM", 10, 150, 100), item("2. LEBAK, 06-10-1991", 10, 300, 130)]
        fields = pair_fields_spatially("SIM", items, {"name": "LEBAK,06-10-1991"})
        assert fields["name"]["value"] == "ROHIM"

    def test_sim_name_above_birth_row(self):
        # name box lost its '1.' prefix but sits directly above the '2.' row
        items = [
            item("MULYONO", 213, 346, 822, h=20),
            item("2. KARANGANYAR, 27-05-1979", 178, 514, 849, h=20),
        ]
        fields = pair_fields_spatially("SIM", items, {})
        assert fields["name"]["value"] == "MULYONO"

    def test_place_name_rejected_as_ktp_nama(self):
        # a kecamatan name in the nama slot is a leak, not a person
        items = [
            item("NIK : 3202041708900001", 36, 500, 170, h=22),
            item(": IRPAN", 276, 400, 204, h=18),
        ]
        fields = pair_fields_spatially("KTP", items, {"nama": "JAMPANGTENGAH"})
        assert fields["nama"]["value"] == "IRPAN"

    def test_garbage_tempat_lahir_not_gazetteer_confirmable(self):
        items = [item("Tempat/Tgl Lahir: BATANG, 01-01-1980", 36, 602, 238, h=18)]
        fields = pair_fields_spatially("KTP", items, {"tempat_lahir": "EEZSO OEO OOOE"})
        assert fields["tempat_lahir"]["value"] == "BATANG"

    def test_kecamatan_unique_gazetteer_fill(self):
        items = [
            item("NIK : 3202041708900001", 36, 500, 170, h=22),
            item("CIKULUR", 40, 160, 500),
            item("random words here", 40, 300, 540),
        ]
        fields = pair_fields_spatially("KTP", items, {})
        assert fields["kecamatan"]["value"] == "CIKULUR"


class TestBerlakuHingga:
    """User finding: rule path took the ISSUE date printed under the KTP
    photo instead of the Berlaku Hingga row; new e-KTPs print SEUMUR HIDUP."""

    def test_label_row_date_beats_photo_issue_date(self):
        # layout mirrors the Anambas card: Berlaku Hingga row on the left,
        # issue date (22-09-2012) under the photo on the right
        items = [
            item("Berlaku Hingga", 40, 200, 660, h=18),
            item(": 26-04-2017", 210, 360, 661, h=18),
            item("KEPULAUAN ANAMBAS", 740, 950, 610, h=16),
            item("22-09-2012", 760, 900, 640, h=16),
        ]
        fields = pair_fields_spatially("KTP", items, {"berlaku_hingga": "22-09-2012"})
        assert fields["berlaku_hingga"]["value"] == "26-04-2017"

    def test_seumur_hidup_extracted(self):
        items = [
            item("Berlaku Hingga", 40, 200, 660, h=18),
            item(": SEUMUR HIDUP", 210, 380, 661, h=18),
            item("19-04-2017", 760, 900, 640, h=16),  # issue date under photo
        ]
        fields = pair_fields_spatially("KTP", items, {"berlaku_hingga": "19-04-2017"})
        assert fields["berlaku_hingga"]["value"] == "SEUMUR HIDUP"

    def test_fills_when_missing(self):
        items = [
            item("Berlaku Hingga : SEUMUR HIDUP", 40, 380, 660, h=18),
        ]
        fields = pair_fields_spatially("KTP", items, {})
        assert fields["berlaku_hingga"]["value"] == "SEUMUR HIDUP"


class TestSimFormats2024AndRedaction:
    """User findings from press photos: gender word beside a redacted name,
    and the late-2024 SIM design where the printed number IS the NIK."""

    def test_gender_word_never_becomes_name(self):
        # 'Nama:' row redacted; 'PRIA' printed beside it on the same row
        items = [
            item("Nama:", 40, 120, 180, h=18),
            item("PRIA", 620, 690, 181, h=18),
            item("Alamat: GENUK KARANGLO RT/RW 001/001", 60, 500, 210, h=18),
        ]
        fields = pair_fields_spatially("SIM", items, {"name": "PRIA"})
        assert "name" not in fields  # empty -> needs_review, never 'PRIA'

    def test_wanita_also_rejected(self):
        fields = pair_fields_spatially("SIM", [item("x", 0, 10, 5)], {"name": "WANITA"})
        assert "name" not in fields

    def test_2024_format_sim_number_is_16_digit_nik(self):
        from app.parser.sim_parser.sim_extractor import SIMExtractor
        from app.models.schemas import ParserContext
        lines = [
            "INDONESIA", "DRIVING LICENSE", "SURAT IZIN MENGEMUDI",
            "3175095801131001",           # printed number == NIK (16 digits)
            "JOHN DOE", "JAKARTA, 17 AGUSTUS 1978",
            "METRO JAYA", "21/12/2028",
        ]
        fields = SIMExtractor().parse(ParserContext(raw_lines=lines, debug=False)).get("fields", {})
        v = fields.get("sim_number") or fields.get("id_number")
        raw = v.get("value") if isinstance(v, dict) else v
        assert raw and "".join(ch for ch in raw if ch.isdigit()) == "3175095801131001"

    def test_colon_residue_name_cleaned_not_deleted(self):
        # extractor left label residue ':PUDIN' — clean it, never delete it
        fields = pair_fields_spatially(
            "SIM", [item("Nama:PUDIN", 40, 200, 180, h=18)],
            {"name": {"value": ":PUDIN", "confidence": 0.85}})
        assert fields["name"]["value"] == "PUDIN"
