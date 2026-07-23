import pytest
from app.utils.detection import detect_document_type
from app.schemas.request_models import DocumentType


def test_detect_ktp():
    lines = [
        "Provinsi DKI Jakarta",
        "Kabupaten/Kota: JAKARTA SELATAN",
        "NIK 3175 0958 0113 1001",
        "Nama : JOHN DOE",
    ]
    assert detect_document_type(lines) == DocumentType.KTP


def test_detect_sim():
    lines = [
        "REPUBLIK INDONESIA",
        "SURAT IZIN MENGEMUDI",
        "Nama/Name: JOHN DOE",
    ]
    assert detect_document_type(lines) == DocumentType.SIM


def test_detect_stnk():
    lines = [
        "SURAT TANDA NOMOR KENDARAAN BERMOTOR",
        "NO. POLISI: B 1234 ABC",
        "Nama: JOHN DOE",
    ]
    assert detect_document_type(lines) == DocumentType.STNK


def test_detect_kir():
    lines = [
        "NOMOR RANGKA: MHKB8DG4JJP123456",
        "NOMOR MESIN: 1NZ-1234567",
        "KIR KENDARAAN",
    ]
    assert detect_document_type(lines) == DocumentType.KIR


def test_detect_unknown():
    lines = [
        "HELLO WORLD",
        "RANDOM CONTENT",
    ]
    assert detect_document_type(lines) == DocumentType.UNKNOWN


def test_kir_requires_word_boundary():
    # "KIRIM"/"SEKIRA" must not be mistaken for KIR
    lines = [
        "JL. KIRIM BARANG NO 5",
        "TOKO SEKIRA JAYA",
    ]
    assert detect_document_type(lines) == DocumentType.UNKNOWN


def test_detect_ktp_with_ocr_digit_noise():
    # Common OCR confusions: 0->O, 1->I should still detect
    lines = [
        "PR0VINSI JAWA TIMUR",
        "N1K : 3578091202990001",
        "KEWARGANEGARAAN WNI",
    ]
    assert detect_document_type(lines) == DocumentType.KTP


def test_detect_sim_with_ocr_digit_noise():
    lines = [
        "SURAT 1ZIN MENGEMUD1",
        "1234-5678-901234",
    ]
    assert detect_document_type(lines) == DocumentType.SIM


def test_ambiguous_rangka_mesin_only_is_unknown():
    # Rangka+mesin alone appear on STNK, KIR, and BPKB; do not guess
    lines = [
        "NOMOR RANGKA X",
        "NOMOR MESIN Y",
    ]
    assert detect_document_type(lines) == DocumentType.UNKNOWN


def test_detailed_result_shape():
    from app.utils.detection import detect_document_type_detailed

    detail = detect_document_type_detailed(["SURAT IZIN MENGEMUDI"])
    assert detail["doc_type"] == DocumentType.SIM
    assert set(detail["scores"].keys()) == {"KTP", "SIM", "STNK", "KIR"}
    assert detail["confidence"] > 0.0
    assert detail["matched_markers"]


def test_detailed_unknown_has_zero_confidence():
    from app.utils.detection import detect_document_type_detailed

    detail = detect_document_type_detailed(["HELLO WORLD"])
    assert detail["doc_type"] == DocumentType.UNKNOWN
    assert detail["confidence"] == 0.0
    assert detail["matched_markers"] == []
