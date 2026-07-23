import os
import sys
import unittest
from unittest.mock import MagicMock

# Add the parent directory to the path to import the parser
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser.ktp_parser.kelurahan_desa_extractor import KelurahanDesaExtractor
from app.models.schemas import ParserContext

class TestKelurahanDesaExtractor(unittest.TestCase):    
    def setUp(self):
        """Set up test fixtures before each test method."""
        self.extractor = KelurahanDesaExtractor()
        self.raw_lines = []
        self.cleaned_lines = []
        self.context = ParserContext(
            raw_lines=self.raw_lines,
            cleaned_lines=self.cleaned_lines,
            debug=True
        )
        # Mock the logger to capture log messages
        self.context.log_info = MagicMock()
        self.context.log_debug = MagicMock()
    
    def test_extract_by_label(self):
        """Test extraction using label patterns."""
        test_cases = [
            # Format: (input_lines, expected_output)
            (["KEL/DESA: JATINEGARA"], "JATINEGARA"),
            (["KELURAHAN DESA: GAMBIR"], "GAMBIR"),
            (["KEL.DESA : MENTENG"], "MENTENG"),
            (["KEL/DESA"], None),  # No value on same line
            (["KEL/DESA", "TANAH ABANG"], "TANAH ABANG"),  # Value on next line
            (["KEL/DESA TANAH ABANG"], "TANAH ABANG"),  # Value after label
            ("KEL/DESA TANAH ABANG KEC. JAKARTA PUSAT".split(" "), "TANAH ABANG"),  # With extra text
            (["KEL/DESA TANAH ABANG, KEC. JAKARTA PUSAT"], "TANAH ABANG"),  # With comma
            (["KEL/DESA TANAH ABANG (KEC. JAKARTA PUSAT)"], "TANAH ABANG"),  # With parentheses
        ]
        
        for lines, expected in test_cases:
            with self.subTest(lines=lines, expected=expected):
                test_lines = lines if isinstance(lines, list) else [lines]
                self.context.raw_lines = test_lines
                self.context.cleaned_lines = [line.strip() for line in test_lines]
                result = self.extractor.extract(self.context)
                self.assertEqual(result, expected)
    
    def test_ocr_errors(self):
        """Test handling of common OCR errors."""
        test_cases = [
            # Format: (input, expected_output)
            ("KEL/DESA JAT1NEG4R4", "JATINEGARA"),  # OCR number substitution
            ("KEL/DESA JATINEG4R4", "JATINEGARA"),
            ("KEL/DESA JATINEGARA ", "JATINEGARA"),  # Trailing space
            ("KEL/DESA JATINEGARA.", "JATINEGARA"),  # Trailing period
            ("KEL/DESA JATINEGARA,", "JATINEGARA"),  # Trailing comma
            ("KEL/DESA  JATINEGARA  ", "JATINEGARA"),  # Extra spaces
        ]
        
        for input_str, expected in test_cases:
            with self.subTest(input=input_str, expected=expected):
                self.context.raw_lines = [input_str]
                self.context.cleaned_lines = [input_str.strip()]
                result = self.extractor.extract(self.context)
                self.assertEqual(result, expected)
    
    def test_invalid_cases(self):
        """Test cases that should not be matched as kelurahan/desa."""
        invalid_cases = [
            "RT/RW 001/002",  # RT/RW pattern
            "NIK 1234567890123456",  # NIK
            "TEMPAT/ TGL LAHIR : JAKARTA, 01-01-1990",  # Birth info
            "ALAMAT : JL. SUDIRMAN NO. 123",  # Address
            "KECAMATAN GAMBIR",  # Kecamatan, not kelurahan/desa
            "KELAMIN LAKI-LAKI",  # Gender
        ]
        
        for case in invalid_cases:
            with self.subTest(case=case):
                self.context.raw_lines = [case]
                result = self.extractor.extract(self.context)
                self.assertIsNone(result, f"Should not match: {case}")
    
    def test_normalization(self):
        """Test normalization of extracted values."""
        test_cases = [
            ("  JATINEGARA  ", "JATINEGARA"),  # Strip spaces
            ("JATINEGARA, JAKARTA", "JATINEGARA"),  # Remove after comma
            ("JATINEGARA (JAKARTA)", "JATINEGARA"),  # Remove parentheses
            ("KEL/DESA JATINEGARA", "JATINEGARA"),  # Remove label
            ("KELURAHAN JATINEGARA", "JATINEGARA"),  # Remove label
            ("DESA JATINEGARA", "JATINEGARA"),  # Remove label
        ]
        
        for input_str, expected in test_cases:
            with self.subTest(input=input_str, expected=expected):
                self.context.raw_lines = [input_str]
                self.context.cleaned_lines = [input_str.strip()]
                result = self.extractor.extract(self.context)
                self.assertEqual(result, expected)
    
    def test_common_villages(self):
        """Test extraction of common village names."""
        common_villages = [
            "JAKARTA PUSAT",
            "JAKARTA SELATAN",
            "BANDUNG KIDUL",
            "SURABAYA UTARA",
        ]
        
        for village in common_villages:
            with self.subTest(village=village):
                self.context.raw_lines = [f"KEL/DESA {village}"]
                result = self.extractor.extract(self.context)
                self.assertEqual(result, village)


if __name__ == "__main__":
    unittest.main()
