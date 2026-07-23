"""Engine bake-off: Google Cloud Vision vs the self-hosted engine.

Runs the SAME labeled eval through GCV's document text detection and
scores with the SAME comparator, so the numbers are directly
comparable. Fair-comparison note: this path uses GCV lines + the rule
parsers (no local field detectors), so compare against the self-hosted
run WITHOUT detectors when judging the raw engines.

Usage:
    set GOOGLE_VISION_API_KEY=...   (Vision API enabled on the project)
    python scripts/eval_gcv.py --labels <dir>

Free tier: first ~1,000 units/month — this eval uses ~41.
"""
import argparse
import base64
import csv
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.utils.detection import detect_document_type_detailed  # noqa: E402
from eval_real_docs import get_value, norm_value, parse_fields  # noqa: E402

GCV_URL = "https://vision.googleapis.com/v1/images:annotate"


def gcv_lines(image_path: Path, api_key: str) -> list:
    """OCR one image via GCV DOCUMENT_TEXT_DETECTION; returns text lines."""
    content = base64.b64encode(image_path.read_bytes()).decode()
    body = {"requests": [{
        "image": {"content": content},
        "features": [{"type": "DOCUMENT_TEXT_DETECTION"}],
    }]}
    r = httpx.post(GCV_URL, params={"key": api_key}, json=body, timeout=60)
    r.raise_for_status()
    resp = r.json()["responses"][0]
    if "error" in resp:
        raise RuntimeError(resp["error"].get("message", "GCV error"))
    text = (resp.get("fullTextAnnotation") or {}).get("text", "")
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    args = ap.parse_args()

    api_key = os.getenv("GOOGLE_VISION_API_KEY", "").strip()
    if not api_key:
        print("GOOGLE_VISION_API_KEY not set — get one at console.cloud.google.com")
        print("(create project -> enable 'Cloud Vision API' -> Credentials -> API key)")
        return 2

    labels_path = Path(args.labels)
    if labels_path.is_dir():
        labels_path = labels_path / "labels.csv"
    img_dir = labels_path.parent

    detect_expect, field_rows = {}, []
    with open(labels_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            f = (row.get("file") or "").strip()
            if not f:
                continue
            if row.get("detect_expect"):
                detect_expect[f] = row["detect_expect"].strip().upper()
            if (row.get("parser") or "").strip() and (row.get("field") or "").strip():
                field_rows.append((f, row["parser"].strip().upper(), row["field"].strip(), row["expected"].strip()))

    t0 = time.time()
    lines_cache = {}
    for i, fname in enumerate(sorted(detect_expect), 1):
        p = img_dir / fname
        if not p.exists():
            continue
        try:
            lines_cache[fname] = gcv_lines(p, api_key)
            print(f"  [{i}] {fname}: {len(lines_cache[fname])} lines", flush=True)
        except Exception as e:
            print(f"  [{i}] {fname}: GCV ERROR {e}", flush=True)
            lines_cache[fname] = []

    det_ok = det_total = 0
    for fname, expect in detect_expect.items():
        lines = lines_cache.get(fname)
        if lines is None:
            continue
        det = detect_document_type_detailed(lines)
        det_total += 1
        got = det["doc_type"].value
        if expect == "MULTI":
            strong = [t for t, s in det["scores"].items() if s >= 3.0]
            det_ok += int(len(strong) >= 2 or got in {"KTP", "SIM"})
        else:
            det_ok += int(got == expect)

    per_type = defaultdict(lambda: [0, 0])
    for fname, parser, field, expected in field_rows:
        lines = lines_cache.get(fname)
        if not lines:
            per_type[parser][1] += 1
            continue
        fields = parse_fields(parser, lines)  # rule parsers only — fair engine comparison
        got = get_value(fields, parser, field)
        per_type[parser][1] += 1
        per_type[parser][0] += int(bool(expected) and norm_value(field, got) == norm_value(field, expected))

    print(f"\nGCV engine ({time.time()-t0:.0f}s): detection {det_ok}/{det_total}")
    tot_ok = tot = 0
    for t, (ok, n) in sorted(per_type.items()):
        tot_ok += ok
        tot += n
        print(f"  {t}: {ok}/{n} ({ok/n:.0%})")
    print(f"  TOTAL fields: {tot_ok}/{tot} ({tot_ok/max(tot,1):.0%})")
    print("\nCompare against the self-hosted engine run WITHOUT field detectors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
