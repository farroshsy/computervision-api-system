"""Field-detector integration logic (detector itself is mocked —
weights are machine-local training artifacts)."""
import numpy as np

from app.parser import field_detector as fd


def test_disabled_without_env(monkeypatch):
    monkeypatch.delenv("FIELD_DETECTOR_STNK_WEIGHTS", raising=False)
    fd._models.clear()
    fields = {"nomor_polisi": {"value": "B 1 A"}}
    out = fd.enrich_with_detector("STNK", b"xx", dict(fields))
    assert out == fields  # untouched


def test_enrich_fills_missing_never_overwrites(monkeypatch):
    detected = {
        "nomor_rangka": {"value": "MHKB3BA1JHK046596", "confidence": 0.91,
                         "provenance": {"method": "field_detector", "class": "nomor_rangka"}},
        "nomor_polisi": {"value": "WRONG PLATE", "confidence": 0.88,
                         "provenance": {"method": "field_detector", "class": "nomor_registrasi"}},
    }
    monkeypatch.setattr(fd, "detect_fields", lambda b, t: detected)
    fields = {"nomor_polisi": {"value": "B 9437 SRU", "confidence": 0.92}}
    out = fd.enrich_with_detector("STNK", b"xx", fields)
    # missing field filled by detector
    assert out["nomor_rangka"]["value"] == "MHKB3BA1JHK046596"
    assert out["nomor_rangka"]["provenance"]["method"] == "field_detector"
    # rule-extracted field NOT overwritten
    assert out["nomor_polisi"]["value"] == "B 9437 SRU"


def test_crop_obb_rectifies_rotation():
    img = np.full((200, 300, 3), 255, dtype=np.uint8)
    pts = np.array([[50, 60], [250, 60], [250, 120], [50, 120]], dtype=np.float32)
    crop = fd._crop_obb(img, pts)
    assert crop is not None
    h, w = crop.shape[:2]
    assert w > h  # long side horizontal


def test_class_map_covers_dataset_classes():
    assert fd.CLASS_MAP["STNK"]["nomor_registrasi"] == "nomor_polisi"
    assert fd.CLASS_MAP["KTP"]["tglLahir"] == "tanggal_lahir"
    assert fd.CLASS_MAP["KTP"]["kel-desa"] == "kelurahan_desa"


def test_pattern_valid_detector_replaces_pattern_invalid_rule(monkeypatch):
    detected = {
        "nomor_rangka": {"value": "MHCFVM34TEJ000358", "confidence": 0.9,
                         "provenance": {"method": "field_detector", "class": "nomor_rangka"}},
        "nomor_polisi": {"value": "AB-8168-BK", "confidence": 0.9,
                         "provenance": {"method": "field_detector", "class": "nomor_registrasi"}},
    }
    monkeypatch.setattr(fd, "detect_fields", lambda b, t: detected)
    fields = {
        # label extractor captured literal label text — pattern-invalid
        "nomor_rangka": {"value": "NIK/VIN", "confidence": 0.8,
                         "provenance": {"method": "label_vin"}},
        # plate regex matched an address fragment — pattern-valid-ish? "NO 3 RT" fails plate shape
        "nomor_polisi": {"value": "NO 3 RT", "confidence": 0.92,
                         "provenance": {"method": "plate_regex"}},
    }
    out = fd.enrich_with_detector("STNK", b"xx", fields)
    assert out["nomor_rangka"]["value"] == "MHCFVM34TEJ000358"
    assert out["nomor_polisi"]["value"] == "AB-8168-BK"


def test_pattern_valid_rule_survives_detector(monkeypatch):
    detected = {"nomor_mesin": {"value": "WRONGENG99", "confidence": 0.9,
                                "provenance": {"method": "field_detector", "class": "nomor_mesin"}}}
    monkeypatch.setattr(fd, "detect_fields", lambda b, t: detected)
    fields = {"nomor_mesin": {"value": "6HK1F001436", "confidence": 0.8,
                              "provenance": {"method": "label_engine"}}}
    out = fd.enrich_with_detector("STNK", b"xx", fields)
    assert out["nomor_mesin"]["value"] == "6HK1F001436"  # both pattern-valid -> keep rule
