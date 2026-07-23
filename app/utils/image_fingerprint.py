"""Perceptual image fingerprints for duplicate detection.

Use case: the client (e.g. a logistics platform) already has a large photo
archive of KTP/SIM/STNK/KIR uploads and wants to know whether a new upload
is the same image as one they already have (re-upload, recompressed,
resized, screenshotted). This module computes a compact fingerprint string
the CLIENT stores in THEIR database — this service keeps nothing, so no
PII ever lives here.

Two complementary 64-bit hashes are combined:
- dHash (difference hash): row-wise brightness gradients. Cheap, robust to
  resizing and recompression.
- pHash (perceptual hash): sign of low-frequency DCT coefficients. Robust
  to brightness/contrast shifts.

Matching = Hamming distance between hashes (count of differing bits out
of 64). Same-image variants land within a few bits; unrelated images are
around 32 bits apart on average.

NOT covered (by design): "same physical card, different photograph" —
that requires embedding models and is a separate roadmap item.
"""
from typing import Dict, Optional

import cv2
import numpy as np

FINGERPRINT_VERSION = "v1"

# Hamming distance thresholds (out of 64 bits) for the best-matching hash.
# <=6: same image with re-encode/resize; <=12: minor edits (crop edge,
# brightness); above: treat as different images.
DUPLICATE_MAX_DISTANCE = 6
NEAR_DUPLICATE_MAX_DISTANCE = 12


def _to_gray(image_bytes: bytes) -> Optional[np.ndarray]:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    return img


def _dhash(gray: np.ndarray) -> int:
    # 9x8 thumbnail -> compare each pixel to its right neighbour -> 64 bits
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    return int(np.packbits(diff).tobytes().hex(), 16)


def _phash(gray: np.ndarray) -> int:
    # 32x32 thumbnail -> DCT -> keep top-left 8x8 low frequencies ->
    # each bit = coefficient above the median (DC term excluded)
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(small.astype(np.float32))
    low = dct[:8, :8].flatten()
    median = np.median(low[1:])
    bits = low > median
    bits[0] = False
    return int(np.packbits(bits).tobytes().hex(), 16)


def compute_fingerprint(image_bytes: bytes) -> Optional[Dict[str, str]]:
    """Compute the fingerprint for an image. None when bytes don't decode.

    Returns {"fingerprint": "v1:<dhash-hex>:<phash-hex>", "dhash": ...,
    "phash": ..., "version": "v1"}.
    """
    gray = _to_gray(image_bytes)
    if gray is None:
        return None
    d = f"{_dhash(gray):016x}"
    p = f"{_phash(gray):016x}"
    return {
        "fingerprint": f"{FINGERPRINT_VERSION}:{d}:{p}",
        "dhash": d,
        "phash": p,
        "version": FINGERPRINT_VERSION,
    }


def parse_fingerprint(fp: str) -> Optional[Dict[str, int]]:
    """Parse 'v1:<dhash>:<phash>' into int hashes. None when malformed."""
    try:
        version, d, p = (fp or "").strip().split(":")
        if version != FINGERPRINT_VERSION or len(d) != 16 or len(p) != 16:
            return None
        return {"dhash": int(d, 16), "phash": int(p, 16)}
    except (ValueError, AttributeError):
        return None


def hamming64(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def compare_fingerprints(fp_a: str, fp_b: str) -> Optional[Dict]:
    """Compare two fingerprint strings.

    Returns {"dhash_distance", "phash_distance", "similarity", "verdict"};
    None when either fingerprint is malformed. similarity is 1.0 for
    identical hashes, decreasing linearly with the best hash distance.
    """
    a, b = parse_fingerprint(fp_a), parse_fingerprint(fp_b)
    if a is None or b is None:
        return None
    dd = hamming64(a["dhash"], b["dhash"])
    dp = hamming64(a["phash"], b["phash"])
    best = min(dd, dp)
    if best <= DUPLICATE_MAX_DISTANCE:
        verdict = "duplicate"
    elif best <= NEAR_DUPLICATE_MAX_DISTANCE:
        verdict = "near_duplicate"
    else:
        verdict = "different"
    return {
        "dhash_distance": dd,
        "phash_distance": dp,
        "similarity": round(1.0 - best / 64.0, 4),
        "verdict": verdict,
    }
