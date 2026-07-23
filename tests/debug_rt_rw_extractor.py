"""
Debug script for RtRwExtractor to help identify why tests are failing.
"""
import sys
import os
from pathlib import Path

# Add the parent directory to the path so we can import the parser
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.parser.ktp_parser.rt_rw_extractor import RtRwExtractor
from app.models.schemas import ParserContext

# Test cases from the test file
test_cases = [
    ("RT/RW : 001/002", "001/002"),
    ("RT/RW: 003/004", "003/004"),
    ("RT.RW : 005/006", "005/006"),
    ("RT RW : 007/008", "007/008"),
    ("RT/RW: 009/010", "009/010"),
    ("RT-RW : 011/012", "011/012"),
    ("RT.RW : 013/014", "013/014"),
    ("RT RW : 015/016", "015/016"),
    ("RT-RW:017/018", "017/018"),
    ("RT.RW:019/020", "019/020"),
    ("RT RW 021/022", "021/022"),
    ("RT  /  RW   :   023 / 024  ", "023/024"),
    ("025/026", "025/026"),
]

def test_extraction():
    extractor = RtRwExtractor()
    
    for input_text, expected in test_cases:
        print(f"\nTesting: {input_text!r}")
        print(f"Expected: {expected!r}")
        
        # Create a context with the test input
        context = ParserContext(
            raw_lines=[input_text],
            cleaned_lines=[input_text],
            debug=True
        )
        
        # Test extract method
        result = extractor.extract(context)
        print(f"Extract result: {result!r}")
        
        # Test _extract_by_label directly
        label_result = extractor._extract_by_label(context)
        print(f"_extract_by_label result: {label_result!r}")
        
        # Test _find_standalone_rt_rw directly
        standalone_result = extractor._find_standalone_rt_rw(context)
        print(f"_find_standalone_rt_rw result: {standalone_result!r}")
        
        # Test _normalize_rt_rw with the input directly
        normalized = extractor._normalize_rt_rw(input_text, context)
        print(f"_normalize_rt_rw result: {normalized!r}")
        
        if result == expected:
            print("[PASS] Test passed!")
        else:
            print("[FAIL] Test failed!")
        
        print("-" * 80)

if __name__ == "__main__":
    test_extraction()
