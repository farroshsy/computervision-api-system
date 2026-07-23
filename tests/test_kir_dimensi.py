"""KIR main dimension: three stacked numbers under 'Dimensi utama', assembled
only when each lands in its own plausible range (rejects the '0009' length
misread and the same-shaped cargo-tub decoy)."""
from app.parser.spatial_pairing import pair_fields_spatially


def it(text, x0, cy):
    return {"text": text, "conf": 0.9, "x0": x0, "x1": x0 + 60, "cy": cy, "h": 18.0}


def dim(fields):
    r = fields.get("dimensi")
    return r.get("value") if isinstance(r, dict) else r


def test_recovers_plausible_column():
    items = [it("Dimensi utama kendaraan", 40, 100),
             it("11950", 80, 130), it("2500", 82, 150), it("4100", 81, 170)]
    assert dim(pair_fields_spatially("KIR", items, {})) == "11950 X 2500 X 4100 mm"


def test_rejects_misread_length():
    # length 6000 read as '0009' -> below range -> no dimensi (safe)
    items = [it("Dimensi utama", 40, 100),
             it("0009", 200, 130), it("2050", 210, 150), it("3200", 205, 170)]
    assert dim(pair_fields_spatially("KIR", items, {})) is None


def test_rejects_out_of_range_width():
    items = [it("3500", 80, 130), it("3500", 82, 150), it("2000", 81, 170)]
    assert dim(pair_fields_spatially("KIR", items, {})) is None


def test_cargo_tub_single_token_not_assembled():
    # the decoy is ONE token, never three stacked -> not a column
    items = [it("Dimensi bak muatan / tangki: (4350 x 2050 x 2000) mm", 40, 200)]
    assert dim(pair_fields_spatially("KIR", items, {})) is None


def test_does_not_override_existing():
    items = [it("11950", 80, 130), it("2500", 82, 150), it("4100", 81, 170)]
    out = pair_fields_spatially("KIR", items, {"dimensi": {"value": "6000 X 2050 X 3200 mm"}})
    assert dim(out) == "6000 X 2050 X 3200 mm"
