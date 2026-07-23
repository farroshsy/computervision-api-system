"""Build the reference-photo STANDARD: one exemplar per document type, chosen
from the customer's own good-quality samples, annotated with the quality
criteria — so anyone collecting NEW data can match "this is what good looks
like" and get clean OCR.

Not a rule, a reference. Old/odd photos still work via /demo; this just shows
the target. Output contains real documents (PII), so it lands in evidence/
(gitignored, runtime-mounted) and is served at /demo/standard — never in the
repo or the image.

    python scripts/build_reference_standard.py --labels <dir>
"""
import argparse
import base64
import csv
import io
import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DOC_ORDER = ["KTP", "SIM", "STNK", "KIR"]
DOC_NAMES = {"KTP": "KTP (e-KTP)", "SIM": "SIM", "STNK": "STNK", "KIR": "KIR (uji berkala)"}

# One source of truth for the criteria (also served at /api/v1/standard).
try:
    from app.services.capture_spec import QUALITY_CRITERIA as CRITERIA
except Exception:
    CRITERIA = ["Seluruh kartu masuk frame", "Rata dari atas", "Terang tanpa silau",
                "Fokus tajam", "Resolusi cukup (>=600px)", "Latar polos", "Foto langsung"]


def _best_exemplar(truth: dict, img_dir: Path):
    """The HIGHEST-resolution good-quality, single-document sample — a standard
    should show the best available, not just the first. Falls back to any."""
    good = [f for f, t in truth.items()
            if not f.startswith("_") and t.get("quality") == "good"
            and not t.get("multi_document")]
    pool = good or [f for f in truth if not f.startswith("_")]
    best, best_short = None, -1
    for f in pool:
        matches = list(img_dir.rglob(f))
        if not matches:
            continue
        try:
            short = min(Image.open(matches[0]).size)
        except Exception:
            continue
        if short > best_short:
            best, best_short = f, short
    return best


def _thumb_b64(path: Path, width=520) -> str:
    img = Image.open(path).convert("RGB")
    if img.width > width:
        img = img.resize((width, int(img.height * width / img.width)))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True, help="labels dir (with per-type truth JSONs alongside images)")
    ap.add_argument("--truth", default=None, help="dir of KTP/SIM/STNK/KIR.json (default: benchmark/truth)")
    args = ap.parse_args()

    img_dir = Path(args.labels)
    if (img_dir / "labels.csv").exists() or img_dir.is_file():
        img_dir = img_dir if img_dir.is_dir() else img_dir.parent
    truth_dir = Path(args.truth) if args.truth else (ROOT / "benchmark" / "truth")

    cards = []
    for dt in DOC_ORDER:
        tf = truth_dir / f"{dt}.json"
        if not tf.exists():
            print(f"skip {dt}: no truth file")
            continue
        truth = json.loads(tf.read_text(encoding="utf-8"))
        fname = _best_exemplar(truth, img_dir)
        if not fname:
            continue
        matches = list(img_dir.rglob(fname))
        if not matches:
            print(f"skip {dt}: image {fname} not found under {img_dir}")
            continue
        p = matches[0]
        img = Image.open(p)
        short = min(img.size)
        cards.append((dt, _thumb_b64(p), short))
        print(f"{dt}: {fname} (short side {short}px)")

    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    crit_html = "".join(f"<li>{esc(c)}</li>" for c in CRITERIA)
    card_html = ""
    for dt, b64, short in cards:
        card_html += (
            f"<figure><figcaption><b>{esc(DOC_NAMES[dt])}</b> — contoh standar "
            f"(resolusi sisi pendek {short}px)</figcaption>"
            f"<img src='data:image/jpeg;base64,{b64}'>"
            f"<ul class='ok'>{crit_html}</ul></figure>")

    html = f"""<!doctype html><html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Standar Foto Referensi — Verifikasi Dokumen</title><style>
  body {{ font-family: system-ui, sans-serif; margin: 1.5rem auto; max-width: 1100px; padding: 0 1rem; color: #222; }}
  h1 {{ font-size: 1.4rem; }} .muted {{ color: #777; font-size: .9rem; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 1.2rem; }}
  figure {{ margin: 0; border: 1px solid #ddd; border-radius: 10px; padding: .8rem; }}
  figure img {{ width: 100%; border-radius: 6px; border: 1px solid #ccc; }}
  figcaption {{ font-size: .9rem; margin-bottom: .5rem; }}
  ul.ok {{ list-style: none; padding: 0; margin: .6rem 0 0; }}
  ul.ok li {{ font-size: .82rem; color: #135f13; padding-left: 1.2rem; position: relative; margin: .2rem 0; }}
  ul.ok li:before {{ content: "✓"; position: absolute; left: 0; font-weight: 700; }}
  .box {{ background: #eef3fc; border-radius: 10px; padding: 1rem; margin: 1rem 0; }}
</style></head><body>
<h1>Standar Foto Referensi</h1>
<p class="muted">Empat contoh di bawah dipilih dari sampel nyata sebagai acuan
kualitas. <b>Bukan kewajiban</b> — foto lama/tak berstruktur tetap bisa
dievaluasi di <a href="/demo">/demo</a>. Tetapi foto BARU yang mengikuti
standar ini menghasilkan OCR paling akurat, karena kesalahan terkonsentrasi
pada foto beresolusi rendah / miring / silau.</p>
<div class="box"><b>Kriteria (berlaku untuk keempatnya):</b><ul class="ok">{crit_html}</ul></div>
<div class="grid">{card_html}</div>
<p class="muted">Berisi dokumen asli — halaman ini dilayani dari folder runtime
(evidence/), tidak pernah masuk repositori atau image Docker. Untuk bantuan
pengambilan langsung, lihat <a href="/capture">/capture</a> (opsional).</p>
</body></html>"""

    ev = ROOT / "evidence"
    ev.mkdir(exist_ok=True)
    out = ev / "reference_standard.html"
    out.write_text(html, encoding="utf-8")
    print(f"\nStandard page: {out}  ({len(cards)} exemplars)  -> served at /demo/standard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
