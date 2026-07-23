"""ISO 6346 container number validation tests."""
import io

import cv2
import numpy as np

from app.utils.container_check import (
    compute_check_digit,
    find_container_numbers,
    validate_container_number,
)


def test_known_valid_number():
    # CSQU3054383 is the canonical ISO 6346 example
    r = validate_container_number("CSQU3054383")
    assert r["valid"] is True
    assert r["expected_check_digit"] == 3


def test_check_digit_mismatch_detected():
    r = validate_container_number("CSQU3054381")
    assert r["valid"] is False
    assert r["reason"] == "check_digit_mismatch"
    assert r["expected_check_digit"] == 3


def test_ocr_misread_is_caught():
    # one digit corrupted (OCR 5 -> 6) must invalidate
    assert validate_container_number("CSQU3064383")["valid"] is False


def test_format_invalid():
    assert validate_container_number("HELLO")["reason"] == "format_invalid"
    assert validate_container_number("")["reason"] == "format_invalid"


def test_spacing_and_dashes_tolerated():
    assert validate_container_number("CSQU 305438-3")["valid"] is True


def test_find_in_ocr_text():
    text = "GATE IN 07:14 CSQU 305438 3 TRUCK B 9437 SRU MSKU 000000 0"
    results = find_container_numbers(text)
    numbers = {r["number"]: r["valid"] for r in results}
    assert "CSQU 305438 3" in numbers and numbers["CSQU 305438 3"] is True


def test_endpoint_text_mode(test_client):
    r = test_client.post("/api/v1/logistics/container", data={"container_number": "CSQU3054383"})
    assert r.status_code == 200
    assert r.json()["results"][0]["valid"] is True


def test_endpoint_requires_input(test_client):
    r = test_client.post("/api/v1/logistics/container")
    assert r.status_code == 400


def test_endpoint_image_mode(test_client):
    img = np.full((160, 900, 3), 255, dtype=np.uint8)
    cv2.putText(img, "CSQU 305438 3", (40, 100), cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 0, 0), 5)
    ok, enc = cv2.imencode(".png", img)
    r = test_client.post("/api/v1/logistics/container",
                         files={"file": ("gate.png", io.BytesIO(enc.tobytes()), "image/png")})
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert any(x["valid"] for x in results), results
