"""Tests for the verification engine and /verify endpoints."""
from datetime import date

from app.services.verification import aggregate_trip, name_similarity, verify_document

TODAY = date(2026, 7, 11)


def test_sim_full_match():
    r = verify_document(
        "SIM",
        {"sim_number": "1427-8708-000059", "name": "AGUS SETYAWAN",
         "class": "BII UMUM", "expiry_date": "01-07-2027"},
        {"sim_number": "1427 8708 000059", "name": "Agus Setyawan"},
        required_classes=["BII", "BII UMUM"],
        today=TODAY,
    )
    assert r["decision"] == "match"
    assert r["reasons"] == []


def test_sim_expired_blocks():
    r = verify_document(
        "SIM",
        {"sim_number": "1", "name": "A B", "class": "BII", "expiry_date": "01-07-2024"},
        {"sim_number": "1"},
        today=TODAY,
    )
    assert r["decision"] == "no_match"
    assert "sim_expired" in r["reasons"]


def test_sim_wrong_class_blocks():
    r = verify_document(
        "SIM",
        {"sim_number": "1", "class": "A", "expiry_date": "01-01-2030"},
        {"sim_number": "1"},
        required_classes=["BII", "BII UMUM"],
        today=TODAY,
    )
    assert r["decision"] == "no_match"
    assert "sim_class_not_allowed" in r["reasons"]


def test_sim_number_mismatch():
    r = verify_document(
        "SIM",
        {"sim_number": "1111-2222-333333", "expiry_date": "01-01-2030"},
        {"sim_number": "9999-8888-777777"},
        today=TODAY,
    )
    assert r["decision"] == "no_match"


def test_unreadable_goes_to_review_not_reject():
    # OCR read nothing useful: never a false no_match
    r = verify_document("SIM", {}, {"sim_number": "123", "name": "BUDI"}, today=TODAY)
    assert r["decision"] == "needs_review"
    assert all(c["status"] == "unreadable" for c in r["checks"])


def test_ktp_glued_ocr_name_still_matches():
    # OCR glues names ("JAKASALMAN"); fuzzy match must survive it
    r = verify_document(
        "KTP",
        {"nik": "3174081705850006", "nama": "JAKASALMAN", "tanggal_lahir": "1985-05-17"},
        {"nik": "3174081705850006", "name": "JAKA SALMAN", "dob": "17-05-1985"},
        today=TODAY,
    )
    assert r["decision"] == "match"


def test_stnk_owner_never_scored():
    # Fleet truck: owner is a PT, driver claim must not be compared to it
    r = verify_document(
        "STNK",
        {"nomor_polisi": "B 9437 SRU", "owner": "PT ADI SARANA ARMADA TBK"},
        {"plate": "B9437SRU"},
        today=TODAY,
    )
    assert r["decision"] == "match"
    assert all(c["field"] != "owner" for c in r["checks"])


def test_kir_expired_blocks():
    r = verify_document(
        "KIR",
        {"vehicle_id": "B 9452 FCG", "valid_until": "13-08-2023"},
        {"plate": "B 9452 FCG"},
        today=TODAY,
    )
    assert r["decision"] == "no_match"
    assert "kir_expired" in r["reasons"]


def test_nothing_to_verify():
    r = verify_document("KTP", {"nik": "123"}, {}, today=TODAY)
    assert r["decision"] == "needs_review"
    assert "nothing_to_verify" in r["reasons"]


def test_name_similarity_variants():
    assert name_similarity("JAKA SALMAN", "JAKASALMAN") == 1.0
    assert name_similarity("AGUS SETYAWAN", "AGUS SETYAWAN") == 1.0
    assert name_similarity("BUDI SANTOSO", "SITI AMINAH") < 0.6


def test_aggregate_trip_decisions():
    m = {"decision": "match", "checks": [], "reasons": []}
    n = {"decision": "no_match", "checks": [], "reasons": []}
    rv = {"decision": "needs_review", "checks": [], "reasons": []}
    assert aggregate_trip({"SIM": m, "STNK": m, "KIR": m})["decision"] == "GO"
    assert aggregate_trip({"SIM": m, "KIR": n})["decision"] == "NO_GO"
    assert aggregate_trip({"SIM": m, "STNK": rv})["decision"] == "REVIEW"
    assert aggregate_trip({})["decision"] == "REVIEW"


def test_verify_trip_endpoint_structure(test_client):
    # Unreadable synthetic image -> REVIEW (correct semantics), response shape stable
    import io
    import cv2
    import numpy as np

    img = np.full((200, 300, 3), 255, dtype=np.uint8)
    ok, enc = cv2.imencode(".jpg", img)
    assert ok
    r = test_client.post(
        "/api/v1/verify/trip",
        files={"sim_file": ("sim.jpg", io.BytesIO(enc.tobytes()), "image/jpeg")},
        data={"driver_name": "BUDI", "sim_number": "123", "required_classes": "BII,BII UMUM"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decision"] in {"GO", "NO_GO", "REVIEW"}
    assert "SIM" in body["documents"]
    assert body["documents"]["SIM"]["decision"] in {"match", "no_match", "needs_review"}


def test_verify_trip_requires_a_document(test_client):
    r = test_client.post("/api/v1/verify/trip", data={"driver_name": "BUDI"})
    assert r.status_code == 400
