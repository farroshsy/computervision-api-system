import argparse
import json
from typing import List
from pathlib import Path
import sys

# Ensure project root is on sys.path for 'app' imports when run as a script
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.models.schemas import ParserContext
from app.parser.ktp_parser.ktp_parser import parse_ktp_fields
from app.parser.sim_parser.sim_extractor import SIMExtractor
from app.parser.stnk_parser.stnk_extractor import STNKExtractor
from app.parser.kir_parser.kir_extractor import KIRExtractor


def load_lines(path: str) -> List[str]:
    with open(path, 'r', encoding='utf-8') as f:
        return [line.rstrip('\n') for line in f]


def main():
    parser = argparse.ArgumentParser(description="Run document extractor on a text file of OCR lines (one per line)")
    parser.add_argument('--type', required=True, choices=['KTP', 'SIM', 'STNK', 'KIR'], help='Document type to parse')
    parser.add_argument('--input', required=True, help='Path to a text file containing OCR lines (UTF-8)')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging in ParserContext')
    args = parser.parse_args()

    lines = load_lines(args.input)
    if args.type == 'KTP':
        result = {"fields": parse_ktp_fields(lines)}
    else:
        ctx = ParserContext(raw_lines=lines, debug=args.debug)
        if args.type == 'SIM':
            extractor = SIMExtractor()
        elif args.type == 'STNK':
            extractor = STNKExtractor()
        else:
            extractor = KIRExtractor()
        result = extractor.parse(ctx)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
