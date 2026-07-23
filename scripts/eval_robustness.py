"""Robustness eval: how does the pipeline behave under photo conditions?

Applies controlled transforms (rotation, mirror, grayscale, darkness,
compression, downscale) to the SAME labeled real images and re-measures
detection + field accuracy per condition. Ground truth is unchanged by
the transforms, so the labeled set multiplies for free.

Usage:
    python scripts/eval_robustness.py --labels <dir-or-csv> [--conditions rot90,mirror]

Output: per-condition table (markdown next to labels + stdout).
"""
import argparse
import csv
import sys
import time
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.services.paddle_ocr import extract_text_from_image  # noqa: E402
from app.utils.detection import detect_document_type_detailed  # noqa: E402
from eval_real_docs import get_value, norm_value, parse_fields  # noqa: E402


def _rot(code):
    return lambda img: cv2.rotate(img, code)


CONDITIONS = {
    "original": lambda img: img,
    "rot90": _rot(cv2.ROTATE_90_CLOCKWISE),
    "rot180": _rot(cv2.ROTATE_180),
    "rot270": _rot(cv2.ROTATE_90_COUNTERCLOCKWISE),
    "mirror": lambda img: cv2.flip(img, 1),
    "grayscale": lambda img: cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR),
    "dark40": lambda img: (img.astype(np.float32) * 0.4).astype(np.uint8),
    "jpeg20": lambda img: cv2.imdecode(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 20])[1], cv2.IMREAD_COLOR),
    "half_res": lambda img: cv2.resize(img, (img.shape[1] // 2, img.shape[0] // 2), interpolation=cv2.INTER_AREA),
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--conditions", default=",".join(CONDITIONS), help="comma-separated subset")
    args = ap.parse_args()

    labels_path = Path(args.labels)
    if labels_path.is_dir():
        labels_path = labels_path / "labels.csv"
    img_dir = labels_path.parent
    conditions = [c.strip() for c in args.conditions.split(",") if c.strip() in CONDITIONS]

    detect_expect: dict = {}
    field_rows = []
    with open(labels_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            f = (row.get("file") or "").strip()
            if not f:
                continue
            if row.get("detect_expect"):
                detect_expect[f] = row["detect_expect"].strip().upper()
            if (row.get("parser") or "").strip() and (row.get("field") or "").strip():
                field_rows.append((f, row["parser"].strip().upper(), row["field"].strip(), row["expected"].strip()))

    files = sorted(detect_expect.keys())
    images = {}
    for fname in files:
        img = cv2.imread(str(img_dir / fname))
        if img is not None:
            images[fname] = img
    print(f"{len(images)} images, {len(field_rows)} fields, conditions: {conditions}", flush=True)

    results = {}
    for cond in conditions:
        t0 = time.time()
        transform = CONDITIONS[cond]
        det_ok = det_total = 0
        f_ok = f_total = 0
        ocr_cache = {}
        for fname, img in images.items():
            variant = transform(img)
            ok, enc = cv2.imencode(".jpg", variant, [cv2.IMWRITE_JPEG_QUALITY, 95])
            if not ok:
                continue
            lines = extract_text_from_image(enc.tobytes())
            ocr_cache[fname] = lines
            det = detect_document_type_detailed(lines)
            expect = detect_expect[fname]
            det_total += 1
            got = det["doc_type"].value
            if expect == "MULTI":
                strong = [t for t, s in det["scores"].items() if s >= 3.0]
                det_ok += int(len(strong) >= 2 or got in {"KTP", "SIM"})
            else:
                det_ok += int(got == expect)
        for fname, parser, field, expected in field_rows:
            lines = ocr_cache.get(fname)
            if lines is None:
                continue
            fields = parse_fields(parser, lines)
            got = get_value(fields, parser, field)
            f_total += 1
            f_ok += int(bool(expected) and norm_value(field, got) == norm_value(field, expected))
        results[cond] = (det_ok, det_total, f_ok, f_total, time.time() - t0)
        print(f"  {cond}: detection {det_ok}/{det_total}, fields {f_ok}/{f_total} ({results[cond][4]:.0f}s)", flush=True)

    out = img_dir / "robustness_report.md"
    lines_out = ["# Robustness report", "",
                 "| condition | detection | fields | field acc |", "|---|---|---|---|"]
    for cond, (d_ok, d_t, fo, ft, _) in results.items():
        lines_out.append(f"| {cond} | {d_ok}/{d_t} | {fo}/{ft} | {fo/ft:.0%} |" if ft else f"| {cond} | {d_ok}/{d_t} | - | - |")
    out.write_text("\n".join(lines_out), encoding="utf-8")
    print(f"Report: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
