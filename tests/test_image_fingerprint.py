"""Tests for perceptual image fingerprints and the /image endpoints."""
import io
import json

import cv2
import numpy as np
import pytest

from app.utils.image_fingerprint import (
    compare_fingerprints,
    compute_fingerprint,
    parse_fingerprint,
)


def _jpeg_bytes(img: np.ndarray, quality: int = 90) -> bytes:
    ok, enc = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    assert ok
    return enc.tobytes()


def _test_card(seed: int = 7) -> np.ndarray:
    """Synthetic 'document photo': gradient background + rectangles + text."""
    rng = np.random.default_rng(seed)
    img = np.tile(np.linspace(60, 200, 480, dtype=np.uint8), (320, 1))
    img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for _ in range(12):
        x, y = int(rng.integers(0, 400)), int(rng.integers(0, 260))
        cv2.rectangle(img, (x, y), (x + 60, y + 30), tuple(int(c) for c in rng.integers(0, 255, 3)), -1)
    cv2.putText(img, "NIK 1234567890123456", (20, 300), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    return img


def test_fingerprint_roundtrip():
    fp = compute_fingerprint(_jpeg_bytes(_test_card()))
    assert fp is not None and fp["version"] == "v1"
    parsed = parse_fingerprint(fp["fingerprint"])
    assert parsed is not None
    assert f"{parsed['dhash']:016x}" == fp["dhash"]


def test_recompressed_image_is_duplicate():
    card = _test_card()
    fp_a = compute_fingerprint(_jpeg_bytes(card, quality=95))["fingerprint"]
    fp_b = compute_fingerprint(_jpeg_bytes(card, quality=40))["fingerprint"]
    assert compare_fingerprints(fp_a, fp_b)["verdict"] == "duplicate"


def test_resized_image_is_duplicate():
    card = _test_card()
    small = cv2.resize(card, (240, 160), interpolation=cv2.INTER_AREA)
    fp_a = compute_fingerprint(_jpeg_bytes(card))["fingerprint"]
    fp_b = compute_fingerprint(_jpeg_bytes(small))["fingerprint"]
    assert compare_fingerprints(fp_a, fp_b)["verdict"] == "duplicate"


def test_different_images_are_different():
    fp_a = compute_fingerprint(_jpeg_bytes(_test_card(seed=7)))["fingerprint"]
    fp_b = compute_fingerprint(_jpeg_bytes(_test_card(seed=99)))["fingerprint"]
    assert compare_fingerprints(fp_a, fp_b)["verdict"] == "different"


def test_malformed_inputs():
    assert compute_fingerprint(b"not an image") is None
    assert parse_fingerprint("garbage") is None
    assert parse_fingerprint("v2:0011223344556677:0011223344556677") is None
    fp = compute_fingerprint(_jpeg_bytes(_test_card()))["fingerprint"]
    assert compare_fingerprints(fp, "garbage") is None


def test_endpoints_fingerprint_and_match(test_client):
    card = _test_card()
    upload = ("card.jpg", io.BytesIO(_jpeg_bytes(card)), "image/jpeg")
    r = test_client.post("/api/v1/image/fingerprint", files={"file": upload})
    assert r.status_code == 200, r.text
    fp = r.json()["fingerprint"]

    other = compute_fingerprint(_jpeg_bytes(_test_card(seed=99)))["fingerprint"]
    upload2 = ("card2.jpg", io.BytesIO(_jpeg_bytes(card, quality=50)), "image/jpeg")
    r2 = test_client.post(
        "/api/v1/image/match",
        files={"file": upload2},
        data={"candidates": json.dumps([other, fp, "malformed"])},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["duplicate_found"] is True
    assert body["candidates_invalid"] == 1
    assert body["matches"][0]["index"] == 1
    assert body["matches"][0]["verdict"] == "duplicate"


def test_match_rejects_bad_candidates_json(test_client):
    upload = ("card.jpg", io.BytesIO(_jpeg_bytes(_test_card())), "image/jpeg")
    r = test_client.post("/api/v1/image/match", files={"file": upload}, data={"candidates": "{not json"})
    assert r.status_code == 400
