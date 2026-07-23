"""Negative/spoof inputs: field keywords without card structure must be
flagged; real card text must not be. Image-level end-to-end lives in
scripts/eval_negatives.py — these are the fast lines-level checks."""
from app.routes.ocr import _build_validation
from app.schemas.request_models import DocumentType
from app.utils.detection import detect_document_type_detailed

TYPED_KTP_SHEET = [
    "Data KTP Karyawan",
    "NIK : 3174041708900001",
    "Nama : BUDI SANTOSO",
    "Alamat : JL MERDEKA NO 1",
    "Agama : ISLAM",
    "Status Perkawinan : KAWIN",
]

REAL_KTP_TEXT = [
    "PROVINSI DKI JAKARTA",
    "KOTA JAKARTA SELATAN",
    "NIK : 3174041708900001",
    "Nama : BUDI SANTOSO",
    "Agama : ISLAM",
]


def reasons_for(doc_type, lines):
    return _build_validation(doc_type, lines).get("reasons") or []


class TestCardHeaderCheck:
    def test_typed_field_sheet_flagged(self):
        # keywords make it DETECT as KTP; the header check must flag it
        det = detect_document_type_detailed(TYPED_KTP_SHEET)
        assert det["doc_type"] == DocumentType.KTP
        assert "missing_card_header" in reasons_for(DocumentType.KTP, TYPED_KTP_SHEET)

    def test_real_ktp_text_not_flagged(self):
        assert "missing_card_header" not in reasons_for(DocumentType.KTP, REAL_KTP_TEXT)

    def test_glued_header_still_counts(self):
        # PaddleOCR drops spaces; the check matches despaced
        lines = ["SURATIZINMENGEMUDI", "1427-8708-000059", "JAKA SALMAN"]
        assert "missing_card_header" not in reasons_for(DocumentType.SIM, lines)

    def test_sim_without_any_header_flagged(self):
        lines = ["Nomor SIM : 1427-8708-000059", "Nama : JAKA SALMAN", "Golongan : BI"]
        assert "missing_card_header" in reasons_for(DocumentType.SIM, lines)

    def test_stnk_police_header_counts(self):
        lines = ["KEPOLISIAN NEGARA REPUBLIK INDONESIA", "NOMOR REGISTRASI : B 9437 SRU"]
        assert "missing_card_header" not in reasons_for(DocumentType.STNK, lines)

    def test_kir_uji_berkala_counts(self):
        lines = ["KARTU UJI BERKALA KENDARAAN BERMOTOR", "NOMOR UJI : TBN5380"]
        assert "missing_card_header" not in reasons_for(DocumentType.KIR, lines)

    def test_empty_text_not_flagged_by_header_check(self):
        # blank input already yields very_low_text_content; header check
        # must not pile on for text that was never there
        reasons = reasons_for(DocumentType.KTP, [])
        assert "missing_card_header" not in reasons
        assert "very_low_text_content" in reasons


class TestSpoofDetection:
    def test_filename_words_alone_do_not_detect(self):
        lines = ["KTP_Budi_Santoso.docx", "Lorem ipsum dolor sit amet"]
        det = detect_document_type_detailed(lines)
        assert det["doc_type"].value == "UNKNOWN"

    def test_receipt_not_detected(self):
        lines = ["INDOMARET", "TOTAL Rp 52.000", "TUNAI Rp 100.000"]
        assert detect_document_type_detailed(lines)["doc_type"].value == "UNKNOWN"


class TestPhotocopySignal:
    def _quality(self, img_array):
        import cv2
        from app.routes.ocr import _compute_image_quality
        ok, buf = cv2.imencode(".png", img_array)
        assert ok
        return _compute_image_quality(buf.tobytes())

    def test_grayscale_copy_flagged(self):
        import numpy as np
        from app.routes.ocr import _build_validation
        # photocopy look: white page, black text, zero color
        img = np.full((700, 1000, 3), 255, dtype=np.uint8)
        img[100:120, 50:900] = 0
        q = self._quality(img)
        assert q["saturation"] < 3.0
        reasons = _build_validation(DocumentType.KTP, ["PROVINSI DKI JAKARTA", "NIK : 3174041708900001"],
                                    image_quality=q).get("reasons") or []
        assert "grayscale_possible_photocopy" in reasons

    def test_colored_photo_not_flagged(self):
        import numpy as np
        from app.routes.ocr import _build_validation
        rng = np.random.default_rng(3)
        img = rng.integers(0, 255, (700, 1000, 3), dtype=np.uint8)
        q = self._quality(img)
        assert q["saturation"] >= 3.0
        reasons = _build_validation(DocumentType.KTP, ["PROVINSI DKI JAKARTA", "NIK : 3174041708900001"],
                                    image_quality=q).get("reasons") or []
        assert "grayscale_possible_photocopy" not in reasons


SIM_TEXT = ["SURAT IZIN MENGEMUDI", "DRIVING LICENSE", "1427-8708-000059",
            "JAKA SALMAN", "BII UMUM"]


class TestDeclaredTypeMismatch:
    def test_sim_photo_declared_ktp_flagged(self):
        # DB column / admin dropdown said KTP; the photo is a SIM
        from app.utils.detection import detect_type_mismatch
        assert detect_type_mismatch("KTP", SIM_TEXT) == "SIM"
        val = _build_validation(DocumentType.KTP, SIM_TEXT)
        assert "document_type_mismatch" in val["reasons"]
        assert val["detected_type"] == "SIM"

    def test_correct_declaration_not_flagged(self):
        from app.utils.detection import detect_type_mismatch
        assert detect_type_mismatch("SIM", SIM_TEXT) is None
        val = _build_validation(DocumentType.SIM, SIM_TEXT)
        assert "document_type_mismatch" not in val["reasons"]
        assert "detected_type" not in val

    def test_blur_never_triggers_mismatch(self):
        # unreadable photo -> UNKNOWN detection; that is a retake case,
        # not a wrong-document case
        from app.utils.detection import detect_type_mismatch
        assert detect_type_mismatch("KTP", ["a3f", "zzz"]) is None

    def test_wallet_photo_with_declared_doc_not_flagged(self):
        # photo contains BOTH documents; the declared one is present ->
        # not a mismatch even if the other scores higher
        from app.utils.detection import detect_type_mismatch
        both = SIM_TEXT + ["PROVINSI DKI JAKARTA", "NIK : 3174041708900001",
                           "Nama : BUDI", "Agama : ISLAM", "KOTA JAKARTA SELATAN"]
        assert detect_type_mismatch("KTP", both) is None
