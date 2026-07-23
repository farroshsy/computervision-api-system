"""Before/after evidence on REAL samples: what each pipeline stage adds.

For one labeled photo per document type, extract fields at three stages:

  rules      parser + regex fallback (+ lexicon corrections)
  +detector  ... + trained YOLO field detector (STNK/KTP, if weights set)
  +boxing    ... + spatial label->value pairing (the full pipeline)

and render expected-vs-got per stage, color-coded, WITH the photo —
proof the improvements happened on real documents, not synthetic ones.

Output lands NEXT TO the labels (real documents are PII and must never
enter the repository): <labels-dir>/evidence_before_after.html

Usage:
    set FIELD_DETECTOR_STNK_WEIGHTS=... / FIELD_DETECTOR_KTP_WEIGHTS=...
    python scripts/eval_before_after.py --labels <dir> [--files a.jpg,b.jpg,...]
"""
import argparse
import base64
import csv
import io
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image

from app.services.paddle_ocr import extract_text_from_image  # noqa: E402
from eval_real_docs import expected_in_raw, get_value, norm_value, parse_fields  # noqa: E402

STAGES = ("rules", "+detector", "+boxing")

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def thumb_b64(path: Path, width=420) -> str:
    img = Image.open(path).convert("RGB")
    if img.width > width:
        img = img.resize((width, int(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


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
    ap.add_argument("--labels", required=True)
    ap.add_argument("--files", default=None, help="comma-separated; default: most-labeled file per type")
    args = ap.parse_args()

    labels_path = Path(args.labels)
    if labels_path.is_dir():
        labels_path = labels_path / "labels.csv"
    img_dir = labels_path.parent

    rows_by_file = defaultdict(list)  # file -> [(parser, field, expected)]
    with open(labels_path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            f = (row.get("file") or "").strip()
            if f and (row.get("parser") or "").strip() and (row.get("field") or "").strip():
                rows_by_file[f].append((row["parser"].strip().upper(), row["field"].strip(),
                                        row["expected"].strip()))

    if args.files:
        chosen = [f.strip() for f in args.files.split(",") if f.strip()]
    else:
        best = {}  # parser -> (n_rows, file)
        for f, rows in rows_by_file.items():
            parser = rows[0][0]
            if len({p for p, _, _ in rows}) > 1:
                continue  # skip multi-doc photos for clean evidence
            if parser not in best or len(rows) > best[parser][0]:
                best[parser] = (len(rows), f)
        chosen = [f for _, f in sorted(best.values(), key=lambda t: -t[0])]

    parts = ["<!doctype html><html lang='id'><head><meta charset='utf-8'>",
             "<title>Bukti sebelum/sesudah — sampel dokumen asli</title><style>",
             "body{font-family:system-ui,sans-serif;margin:2rem;color:#222;max-width:1200px}",
             "table{border-collapse:collapse;margin:.6rem 0;width:100%}",
             "th,td{border:1px solid #ddd;padding:.35rem .6rem;font-size:.85rem;text-align:left}",
             "th{background:#f0f0f0}",
             "td.ok{background:#d3f5d3;color:#135f13}",
             "td.miss{background:#fbd3d3;color:#7c1010}",
             "td.part{background:#fdeec8;color:#7a5b00}",
             "td.mono{font-family:Consolas,monospace}",
             ".case{display:flex;gap:1.5rem;align-items:flex-start;margin:2rem 0;",
             "border-top:2px solid #ccc;padding-top:1.5rem;flex-wrap:wrap}",
             ".case>img{border-radius:8px;border:1px solid #ccc}",
             ".case>div{flex:1;min-width:480px}",
             "</style></head><body>",
             "<h1>Tahapan pipeline pada dokumen asli — nilai seharusnya vs hasil ekstraksi</h1>",
             "<p>rules = parser + regex · +detector = detektor field terlatih (YOLO) · ",
             "+boxing = pemetaan label→nilai berbasis geometri (pipeline penuh). ",
             "Berisi data pribadi — simpan bersama data, jangan pernah masuk repositori.</p>"]

    totals = {s: [0, 0] for s in STAGES}
    raw_totals: dict = {}
    for fname in chosen:
        p = img_dir / fname
        rows = rows_by_file.get(fname, [])
        if not p.exists() or not rows:
            print(f"skip {fname}: missing file or labels")
            continue
        parser = rows[0][0]
        try:
            import shutil
            samples = Path(__file__).resolve().parent.parent / "evidence" / "samples"
            samples.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, samples / fname)
        except OSError:
            pass
        print(f"[{parser}] {fname}: OCR...", flush=True)
        lines, items = extract_text_from_image(str(p), return_items=True)
        stage_fields = {
            "rules": parse_fields(parser, lines),
            "+detector": parse_fields(parser, lines, image_path=p),
            "+boxing": parse_fields(parser, lines, image_path=p, items=items),
        }
        parts.append(f"<div class='case'><img src='data:image/jpeg;base64,{thumb_b64(p)}' width='420'>")
        parts.append(f"<div><h2>{parser} — {esc(fname)}</h2><table><tr><th>field</th><th>seharusnya</th>"
                     "<th>terbaca OCR mentah?</th>"
                     + "".join(f"<th>{s}</th>" for s in STAGES) + "</tr>")
        for _, field, expected in rows:
            raw_verdict = expected_in_raw(field, expected, lines)
            raw_totals[raw_verdict] = raw_totals.get(raw_verdict, 0) + 1
            raw_cls = {"READ": "ok", "PARTIAL": "part", "NOT READ": "miss"}[raw_verdict]
            raw_label = {"READ": "TERBACA", "PARTIAL": "SEBAGIAN", "NOT READ": "TAK TERBACA"}[raw_verdict]
            cells = f"<td class='{raw_cls}'>{raw_label}</td>"
            for s in STAGES:
                got = get_value(stage_fields[s], parser, field) or ""
                ok = bool(expected) and norm_value(field, got) == norm_value(field, expected)
                totals[s][0] += int(ok)
                totals[s][1] += 1
                cells += f"<td class='mono {'ok' if ok else 'miss'}'>{esc(got)}</td>"
            parts.append(f"<tr><td>{esc(field)}</td><td class='mono'>{esc(expected)}</td>{cells}</tr>")
        parts.append("</table><details><summary>baris OCR mentah (keluaran penuh mesin OCR)</summary><pre>"
                     + esc("\n".join(lines)) + "</pre></details></div></div>")

    parts.append("<h2>Total pada sampel yang ditampilkan</h2><table><tr><th>terbaca di OCR mentah</th>"
                 + "".join(f"<th>{s}</th>" for s in STAGES) + "</tr><tr>"
                 + f"<td>{raw_totals.get('READ', 0)} terbaca / {raw_totals.get('PARTIAL', 0)} sebagian / "
                   f"{raw_totals.get('NOT READ', 0)} tak terbaca</td>"
                 + "".join(f"<td>{ok}/{n} ({ok / max(n, 1):.0%})</td>" for ok, n in
                           (totals[s] for s in STAGES))
                 + "</tr></table>"
                 "<p>Field yang TERBACA di OCR mentah tetapi meleset = celah ekstraksi (tugas lapisan kami). "
                 "Field TAK TERBACA = keterbatasan pengenalan/kualitas foto yang tidak bisa diperbaiki parsing; "
                 "butuh foto lebih baik, detektor terlatih, atau mesin OCR berbeda.</p>"
                 "</body></html>")
    out = img_dir / "evidence_before_after.html"
    out.write_text("".join(parts), encoding="utf-8")
    _copy_to_evidence(out)
    print(f"\nEvidence page: {out}")
    print(f"  raw OCR    {raw_totals.get('READ', 0)} read / {raw_totals.get('PARTIAL', 0)} partial / "
          f"{raw_totals.get('NOT READ', 0)} not read")
    for s in STAGES:
        ok, n = totals[s]
        print(f"  {s:10} {ok}/{n} ({ok / max(n, 1):.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
