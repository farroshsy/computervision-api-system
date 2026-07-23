import argparse
import os
from pathlib import Path
from typing import List
import sys

# Ensure project root is on sys.path for 'app' imports when run as a script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.paddle_ocr import extract_text_from_image


def collect_images(input_dir: Path) -> List[Path]:
    exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff'}
    files: List[Path] = []
    for p in input_dir.rglob('*'):
        if p.is_file() and p.suffix.lower() in exts:
            files.append(p)
    return files


def dump_lines_for_image(img_path: Path, out_path: Path) -> int:
    lines = extract_text_from_image(str(img_path))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        for line in lines:
            f.write(line.strip() + '\n')
    return len(lines)


def main():
    parser = argparse.ArgumentParser(description="Dump OCR lines for images in a directory")
    parser.add_argument('--type', required=True, choices=['KTP', 'SIM', 'STNK', 'KIR'], help='Document type (for output subfolder naming)')
    parser.add_argument('--input-dir', required=True, help='Directory containing images to OCR')
    parser.add_argument('--output-dir', default='newdata/result', help='Base output directory for dumped lines')
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    output_base = Path(args.output_dir).resolve()
    out_dir = output_base / args.type / 'lines'

    images = collect_images(input_dir)
    if not images:
        print(f"No images found in {input_dir}")
        return

    total_lines = 0
    for img in images:
        rel = img.relative_to(input_dir)
        out_txt = out_dir / rel.with_suffix('.txt')
        count = dump_lines_for_image(img, out_txt)
        total_lines += count
        print(f"Dumped {count:4d} lines -> {out_txt}")

    print(f"Done. {len(images)} images processed. {total_lines} lines total.")


if __name__ == '__main__':
    main()
