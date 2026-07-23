"""Evaluate the OCR+parser pipeline against labeled real document photos.

Usage:
    python scripts/eval_real_docs.py --labels <dir-or-csv> [--out results.md]

The labels CSV lives NEXT TO the images, outside this repository — real
KYC documents are PII and must never be committed. Long format:

    file,detect_expect,parser,field,expected

- detect_expect: expected detect_document_type outcome for the whole image
  (KTP/SIM/STNK/KIR, or MULTI when the photo contains several documents;
  detection scoring counts MULTI as correct when >=2 types score strongly).
- parser/field/expected: ground-truth field rows; parser says which document
  parser the field belongs to. Rows with empty parser are detection-only.

Outputs per-field comparison and per-doc-type accuracy, plus a summary
table (markdown) suitable for the README/RFC.
"""
import argparse
import csv
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.paddle_ocr import extract_text_from_image  # noqa: E402
from app.utils.detection import detect_document_type_detailed  # noqa: E402
from app.schemas.request_models import DocumentType  # noqa: E402
from app.parser.ktp_parser.ktp_parser import parse_ktp_fields  # noqa: E402
from app.parser.sim_parser.sim_extractor import SIMExtractor  # noqa: E402
from app.parser.stnk_parser.stnk_extractor import STNKExtractor  # noqa: E402
from app.parser.kir_parser.kir_extractor import KIRExtractor  # noqa: E402
from app.models.schemas import ParserContext  # noqa: E402
from app.utils.id_reference import fuzzy_correct_fields  # noqa: E402

# Extracted-field aliases per (parser, label-field)
ALIASES = {
    ("SIM", "sim_number"): ("sim_number", "id_number"),
    ("SIM", "name"): ("name", "nama"),
    ("SIM", "class"): ("class",),
    ("SIM", "expiry_date"): ("expiry_date", "valid_to"),
    ("STNK", "nomor_polisi"): ("nomor_polisi", "plate_number"),
    ("STNK", "owner"): ("owner", "owner_name"),
    ("STNK", "nomor_rangka"): ("nomor_rangka", "vin_chassis"),
    ("STNK", "nomor_mesin"): ("nomor_mesin", "engine_number"),
    ("KIR", "vehicle_id"): ("vehicle_id",),
    ("KIR", "valid_until"): ("valid_until", "masa_berlaku"),
}


def norm_value(field: str, value) -> str:
    """Normalize for comparison: case/space-insensitive; digits-only for
    numeric ids; dashes-insensitive for SIM numbers; date formats unified."""
    s = str(value or "").upper().strip()
    if not s:
        return ""
    if field in {"nik", "sim_number", "nomor_mesin"}:
        return re.sub(r"[^A-Z0-9]", "", s)
    if field in {"nomor_polisi", "vehicle_id", "nomor_rangka"}:
        return re.sub(r"[^A-Z0-9]", "", s)
    if field in {"tanggal_lahir", "expiry_date", "valid_until"}:
        digits = re.findall(r"\d+", s)
        if len(digits) == 3:
            a, b, c = digits
            if len(a) == 4:  # YYYY-MM-DD
                return f"{int(c):02d}-{int(b):02d}-{a}"
            return f"{int(a):02d}-{int(b):02d}-{c}"
        return s
    if field in {"nama", "name", "owner", "owner_name", "tempat_lahir"}:
        # PaddleOCR often drops spaces; JAKASALMAN == JAKA SALMAN
        return re.sub(r"[^A-Z0-9]", "", s)
    return re.sub(r"\s+", " ", s)


_RAW_DATE_FIELDS = {"valid_until", "expiry_date", "tanggal_lahir", "tax_valid_to"}


def expected_in_raw(field: str, expected: str, lines) -> str:
    """Was the ground-truth value READABLE in the raw OCR at all?
    READ = engine read it (a miss is OUR extraction problem);
    PARTIAL = fragments only; NOT READ = recognition/photo limit."""
    import difflib
    exp_norm = re.sub(r"[^A-Z0-9]", "", str(expected).upper())
    if not exp_norm:
        return "NOT READ"
    if field in _RAW_DATE_FIELDS:
        from app.utils.validators import normalize_expiry_date
        want = normalize_expiry_date(expected)
        for ln in lines:
            for m in re.finditer(
                    r"\d{1,2}[-/. ]\d{1,2}[-/. ](?:19|20)\d{2}|\d{1,2}\s?[A-Za-z]{3,9}\s?(?:19|20)\d{2}",
                    ln):
                if want and normalize_expiry_date(m.group(0).replace(".", "-")) == want:
                    return "READ"
        return "NOT READ"
    joined = re.sub(r"[^A-Z0-9]", "", " ".join(lines).upper())
    if exp_norm in joined:
        return "READ"
    best = 0.0
    for ln in lines:
        ln_norm = re.sub(r"[^A-Z0-9]", "", ln.upper())
        if not ln_norm:
            continue
        best = max(best, difflib.SequenceMatcher(None, exp_norm, ln_norm).ratio())
        if exp_norm[:max(4, len(exp_norm) // 2)] in ln_norm:
            best = max(best, 0.75)
    return "PARTIAL" if best >= 0.7 else "NOT READ"


def parse_fields(parser: str, lines, image_path=None, items=None):
    """Mirror the API path: parser + regex fallback + field detector + lexicons."""
    from app.routes.ocr import _regex_fallback_fields

    if parser == "KTP":
        fields = parse_ktp_fields(lines)
        fields = fields if isinstance(fields, dict) else {}
    else:
        ctx = ParserContext(raw_lines=lines, debug=False)
        ext = {"SIM": SIMExtractor, "STNK": STNKExtractor, "KIR": KIRExtractor}[parser]()
        fields = ext.parse(ctx).get("fields", {})
    try:
        fields = _regex_fallback_fields(DocumentType(parser), lines, fields)
    except Exception:
        pass
    if items and parser in ("KIR", "STNK", "KTP", "SIM"):
        try:
            from app.parser.spatial_pairing import pair_fields_spatially
            fields = pair_fields_spatially(parser, items, fields)
        except Exception:
            pass
    if image_path is not None and parser in ("STNK", "KTP"):
        try:
            from app.parser.field_detector import enrich_with_detector
            fields = enrich_with_detector(parser, open(image_path, "rb").read(), fields)
        except Exception:
            pass
    if image_path is not None and items and parser == "SIM":
        try:
            from app.parser.sim_expiry_zone import recover_sim_expiry
            fields = recover_sim_expiry(open(image_path, "rb").read(), items, fields)
        except Exception:
            pass
    return fuzzy_correct_fields(fields)


def get_value(fields: dict, parser: str, field: str):
    for key in ALIASES.get((parser, field), (field,)):
        v = fields.get(key)
        raw = v.get("value") if isinstance(v, dict) else v
        if raw:
            return raw
    return None


def _write_html_report(img_dir, det_ok, det_total, per_type, records) -> None:
    """Visual report: expected vs extracted per field, color-coded.
    Contains PII values — lives next to the labels, never in the repo."""
    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'><title>Laporan evaluasi</title><style>",
        "body{font-family:system-ui,sans-serif;margin:2rem;color:#222}",
        "table{border-collapse:collapse;width:100%;margin:1rem 0}",
        "th,td{border:1px solid #ddd;padding:.4rem .6rem;font-size:.85rem;text-align:left}",
        "th{background:#f0f0f0}",
        "tr.ok td.result{background:#d3f5d3;color:#135f13;font-weight:600}",
        "tr.miss td.result{background:#fbd3d3;color:#7c1010;font-weight:600}",
        "td.got,td.exp{font-family:Consolas,monospace}",
        ".tile{display:inline-block;background:#f6f6f6;border-radius:8px;padding:.6rem 1.2rem;margin:.3rem}",
        ".tile b{font-size:1.5rem;display:block}",
        "</style></head><body><h1>Evaluasi dokumen asli — nilai seharusnya vs hasil ekstraksi</h1>",
        f"<div class='tile'><b>{det_ok}/{det_total}</b>deteksi jenis</div>",
    ]
    for t, (okc, total) in sorted(per_type.items()):
        parts.append(f"<div class='tile'><b>{okc}/{total}</b>{t} fields</div>")
    cur = None
    for parser, fname, field, expected, got, ok in sorted(records):
        if parser != cur:
            if cur is not None:
                parts.append("</table>")
            parts.append(f"<h2>{parser}</h2><table><tr><th>foto</th><th>field</th>"
                         "<th>seharusnya</th><th>terekstrak</th><th>hasil</th></tr>")
            cur = parser
        parts.append(f"<tr class='{'ok' if ok else 'miss'}'><td>{esc(fname)}</td><td>{esc(field)}</td>"
                     f"<td class='exp'>{esc(expected)}</td><td class='got'>{esc(got)}</td>"
                     f"<td class='result'>{'OK' if ok else 'MELESET'}</td></tr>")
    if cur is not None:
        parts.append("</table>")
    parts.append("<p>Dibuat oleh scripts/eval_real_docs.py — memuat data pribadi; simpan di luar repositori.</p></body></html>")
    (img_dir / "eval_report.html").write_text("".join(parts), encoding="utf-8")
    print(f"HTML report: {img_dir / 'eval_report.html'}", flush=True)
    _copy_to_evidence(img_dir / "eval_report.html")


def _copy_to_evidence(src_path) -> None:
    """Also drop the HTML into <repo>/evidence so the API serves it at
    /demo/evidence — runtime-mounted, gitignored (PII never in the image)."""
    import shutil
    from pathlib import Path
    ev = Path(__file__).resolve().parent.parent / "evidence"
    try:
        ev.mkdir(exist_ok=True)
        shutil.copy2(src_path, ev / Path(src_path).name)
        print(f"copied to {ev / Path(src_path).name}")
    except OSError as exc:
        print(f"evidence copy skipped: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True, help="labels.csv path or its directory")
    ap.add_argument("--out", default=None, help="markdown report path (default: <labels-dir>/eval_report.md)")
    args = ap.parse_args()

    labels_path = Path(args.labels)
    if labels_path.is_dir():
        labels_path = labels_path / "labels.csv"
    img_dir = labels_path.parent
    out_path = Path(args.out) if args.out else img_dir / "eval_report.md"

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
    print(f"Evaluating {len(files)} images, {len(field_rows)} labeled fields", flush=True)

    ocr_cache: dict = {}
    items_cache: dict = {}
    detect_results: dict = {}
    t0 = time.time()
    for i, fname in enumerate(files, 1):
        p = img_dir / fname
        if not p.exists():
            print(f"  MISSING {fname}", flush=True)
            continue
        lines, items = extract_text_from_image(str(p), return_items=True)
        ocr_cache[fname] = lines
        items_cache[fname] = items
        det = detect_document_type_detailed(lines)
        detect_results[fname] = det
        print(f"  [{i}/{len(files)}] {fname}: {len(lines)} lines -> {det['doc_type'].value} {det['scores']}", flush=True)

    # Detection scoring
    det_ok = det_total = 0
    det_lines_out = []
    for fname, expect in detect_expect.items():
        det = detect_results.get(fname)
        if det is None:
            continue
        det_total += 1
        got = det["doc_type"].value
        if expect == "MULTI":
            strong = [t for t, s in det["scores"].items() if s >= 3.0]
            ok = len(strong) >= 2 or got in {"KTP", "SIM"}
        else:
            ok = got == expect
        det_ok += int(ok)
        det_lines_out.append(f"| {fname} | {expect} | {got} | {'ok' if ok else 'MISS'} |")

    # Field scoring
    per_type = defaultdict(lambda: [0, 0])
    per_field = defaultdict(lambda: [0, 0])
    field_lines_out = []
    html_records = []
    miss_records = []
    for fname, parser, field, expected in field_rows:
        lines = ocr_cache.get(fname)
        if lines is None:
            continue
        fields = parse_fields(parser, lines, image_path=img_dir / fname, items=items_cache.get(fname))
        got = get_value(fields, parser, field)
        ok = norm_value(field, got) == norm_value(field, expected) and bool(expected)
        per_type[parser][1] += 1
        per_type[parser][0] += int(ok)
        per_field[(parser, field)][1] += 1
        per_field[(parser, field)][0] += int(ok)
        field_lines_out.append(
            f"| {fname} | {parser} | {field} | {expected} | {got or ''} | {'ok' if ok else 'MISS'} |")
        html_records.append((parser, fname, field, expected, got or "", ok))
        if not ok:
            miss_records.append((("EMPTY" if not got else "WRONG"),
                                 expected_in_raw(field, expected, lines),
                                 parser, fname, field, expected, got or ""))

    elapsed = time.time() - t0
    report = ["# Real-document eval report", "",
              f"- images: {det_total}, labeled fields: {len(field_rows)}, runtime: {elapsed:.0f}s",
              f"- detection accuracy: **{det_ok}/{det_total}**", "",
              "## Per-type field accuracy", "", "| type | correct | total | acc |", "|---|---|---|---|"]
    for t, (ok, total) in sorted(per_type.items()):
        report.append(f"| {t} | {ok} | {total} | {ok/total:.0%} |")
    report += ["", "## Per-field accuracy", "", "| type | field | correct | total | acc |", "|---|---|---|---|---|"]
    for (t, fld), (ok, total) in sorted(per_field.items()):
        report.append(f"| {t} | {fld} | {ok} | {total} | {ok/total:.0%} |")
    report += ["", "## Detection detail", "", "| file | expected | got | result |", "|---|---|---|---|"]
    report += det_lines_out
    report += ["", "## Field detail", "", "| file | parser | field | expected | got | result |", "|---|---|---|---|---|---|"]
    report += field_lines_out

    # Miss forensics: EMPTY vs WRONG x readable-in-raw. READ/PARTIAL rows
    # are OUR extraction gaps; NOT READ is a recognition limit.
    breakdown = defaultdict(int)
    for kind, verdict, *_rest in miss_records:
        breakdown[(kind, verdict)] += 1
    actionable = [m for m in miss_records if m[1] in ("READ", "PARTIAL")]
    report += ["", "## Miss forensics (kind x raw-OCR readability)", "",
               "| kind | raw verdict | count |", "|---|---|---|"]
    for (kind, verdict), n in sorted(breakdown.items()):
        report.append(f"| {kind} | {verdict} | {n} |")
    report += ["", "### Actionable misses (value visible in raw OCR)", "",
               "| kind | raw | file | parser | field | expected | got |",
               "|---|---|---|---|---|---|---|"]
    for kind, verdict, parser, fname, field, expected, got in actionable:
        report.append(f"| {kind} | {verdict} | {fname} | {parser} | {field} | {expected} | {got} |")

    out_path.write_text("\n".join(report), encoding="utf-8")
    _write_html_report(img_dir, det_ok, det_total, per_type, html_records)
    print(f"\nDetection: {det_ok}/{det_total}", flush=True)
    for t, (ok, total) in sorted(per_type.items()):
        print(f"{t}: {ok}/{total} ({ok/total:.0%})", flush=True)
    for (t, fld), (ok, total) in sorted(per_field.items()):
        print(f"  {t}.{fld}: {ok}/{total}", flush=True)
    print("\nMISS FORENSICS (kind x raw readability):", flush=True)
    for (kind, verdict), n in sorted(breakdown.items()):
        print(f"  {kind:6} {verdict:9} {n}", flush=True)
    print("  actionable (READ/PARTIAL):", flush=True)
    for kind, verdict, parser, fname, field, expected, got in actionable:
        print(f"    {kind:6} {verdict:9} {parser:5} {field:18} exp={expected!r} got={got!r} ({fname})",
              flush=True)
    print(f"Report: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
