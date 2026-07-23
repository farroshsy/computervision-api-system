"""Negative-input eval: the system must REJECT or FLAG what is not a document.

Real-document accuracy says nothing about what happens when someone
uploads a receipt, a blank page, or a Word file with KTP data typed
into it. This harness GENERATES those inputs (synthetic, zero PII),
runs the real pipeline (OCR -> detection -> validation), and reports
the verdict per case:

  REJECTED  detection returned UNKNOWN                      (good)
  FLAGGED   detected as a doc type but validation raised
            missing_card_header / other reasons -> review   (good)
  PASSED    detected clean                                  (bad for a negative)

Usage:
    python scripts/eval_negatives.py [--keep]
"""
import argparse
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.paddle_ocr import extract_text_from_image  # noqa: E402
from app.utils.detection import detect_document_type_detailed  # noqa: E402
from app.routes.ocr import _build_validation  # noqa: E402


def _font(size: int):
    for candidate in (r"C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _page(lines, title=None, size=(1000, 1400)):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    y = 80
    if title:
        d.text((80, y), title, fill="black", font=_font(34))
        y += 90
    body = _font(28)
    for ln in lines:
        d.text((80, y), ln, fill="black", font=body)
        y += 52
    return img


def build_cases(out_dir: Path):
    """Each case: (name, expected_verdicts, path). Expected is a set of
    acceptable outcomes — REJECTED is always fine for a negative."""
    lorem = ["Lorem ipsum dolor sit amet, consectetur", "adipiscing elit, sed do eiusmod tempor",
             "incididunt ut labore et dolore magna."]
    typed_fields = ["NIK : 3174041708900001", "Nama : BUDI SANTOSO",
                    "Alamat : JL MERDEKA NO 1", "Agama : ISLAM",
                    "Status Perkawinan : KAWIN", "Kewarganegaraan : WNI"]
    cases = []

    def add(name, img, expected):
        p = out_dir / f"{name}.png"
        img.save(p)
        cases.append((name, expected, p))

    add("word_doc_ktp_filename", _page(lorem, title="KTP_Budi_Santoso.docx"), {"REJECTED"})
    add("word_doc_typed_fields", _page(typed_fields, title="Data KTP Karyawan"), {"REJECTED", "FLAGGED"})
    # documented limitation: a replica that also types the card header
    # passes text-level checks — physical anti-spoof is out of scope
    add("word_doc_full_replica",
        _page(["PROVINSI DKI JAKARTA", "KOTA JAKARTA SELATAN"] + typed_fields),
        {"REJECTED", "FLAGGED", "PASSED_KNOWN_LIMIT"})
    add("blank_page", Image.new("RGB", (1000, 1400), "white"), {"REJECTED"})
    add("random_noise", Image.fromarray(
        np.random.default_rng(7).integers(0, 255, (800, 1000, 3), dtype=np.uint8)  # noqa: NPY002
    ), {"REJECTED"})
    grad = np.tile(np.linspace(0, 255, 1000, dtype=np.uint8), (800, 1))
    add("gradient_photo", Image.fromarray(np.stack([grad, grad // 2, 255 - grad], axis=-1)), {"REJECTED"})
    add("receipt", _page(["INDOMARET", "ROTI TAWAR      12.000", "SUSU UHT        18.500",
                          "TOTAL Rp 52.000", "TUNAI Rp 100.000", "KEMBALI Rp 48.000"]), {"REJECTED"})
    add("business_letter", _page(["Kepada Yth. Bapak/Ibu Pimpinan", "Dengan hormat,",
                                  "bersama surat ini kami sampaikan", "penawaran kerja sama layanan",
                                  "Hormat kami,", "PT MAJU JAYA SENTOSA"]), {"REJECTED"})
    return cases


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep", action="store_true", help="keep generated images")
    args = ap.parse_args()

    out_dir = Path(tempfile.mkdtemp(prefix="neg_eval_"))
    cases = build_cases(out_dir)
    print(f"generated {len(cases)} negatives in {out_dir}\n")

    ok = 0
    for name, expected, path in cases:
        lines = extract_text_from_image(str(path))
        det = detect_document_type_detailed(lines)
        doc_type = det["doc_type"]
        if doc_type.value == "UNKNOWN":
            verdict = "REJECTED"
            detail = ""
        else:
            validation = _build_validation(doc_type, lines)
            reasons = validation.get("reasons") or []
            verdict = "FLAGGED" if reasons else (
                "PASSED_KNOWN_LIMIT" if "PASSED_KNOWN_LIMIT" in expected else "PASSED")
            detail = f" as {doc_type.value} reasons={reasons}"
        good = verdict in expected
        ok += int(good)
        print(f"  {'OK  ' if good else 'BAD '} {name:24} -> {verdict}{detail}")

    print(f"\n{ok}/{len(cases)} negatives handled correctly")
    if not args.keep:
        for _, _, p in cases:
            p.unlink(missing_ok=True)
        out_dir.rmdir()
    return 0 if ok == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
