"""
Tests for the modular KTP parser.
"""

import unittest
import os
import sys
from pathlib import Path

# Add the parent directory to the path so we can import the parser
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.parser.ktp_parser.ktp_parser import KTPParser, parse_ktp_fields
from app.parser.ktp_parser.nik_extractor import NIKExtractor
from app.parser.ktp_parser.name_extractor import NameExtractor
from app.parser.ktp_parser.alamat_extractor import AlamatExtractor
from app.models.schemas import ParserContext

class TestNameExtractor(unittest.TestCase):
    """Tests for the name extraction functionality"""
    
    def setUp(self):
        self.extractor = NameExtractor()
        self.context = ParserContext(raw_lines=[], cleaned_lines=[], debug=True)
    
    def test_extract_name_label_with_colon(self):
        """Test extraction of name with label and colon"""
        self.context.raw_lines = ["Nama: JOHN DOE"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JOHN DOE")
    
    def test_extract_name_label_with_space_before_colon(self):
        """Test extraction of name with space before colon"""
        self.context.raw_lines = ["Nama : JANE DOE"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JANE DOE")
    
    def test_extract_name_label_without_space_after_colon(self):
        """Test extraction of name without space after colon"""
        self.context.raw_lines = ["Nama:JOHN DOE"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JOHN DOE")
    
    def test_extract_name_on_next_line_after_label(self):
        """Test extraction of name on the line after label"""
        self.context.raw_lines = ["Nama:", "JOHN DOE"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JOHN DOE")
    
    def test_extract_name_on_next_line_after_label_with_colon(self):
        """Test extraction when next line starts with colon"""
        self.context.raw_lines = ["Nama", ":JOHN DOE"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JOHN DOE")
    
    def test_extract_name_with_typo_in_label(self):
        """Test extraction with common OCR typos in label"""
        self.context.raw_lines = ["Kama :AMIN TOHARI"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "AMIN TOHARI")
    
    def test_skip_lines_with_numbers(self):
        """Test that lines with numbers are skipped"""
        self.context.raw_lines = ["NIK 1234567890123456", "Nama: JOHN DOE 123"]
        result = self.extractor.extract(self.context)
        self.assertIsNone(result)  # Should skip line with numbers
    
    def test_skip_header_terms(self):
        """Test that header terms are skipped"""
        self.context.raw_lines = ["PROVINSI JAWA TIMUR", "Nama: JOHN DOE"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JOHN DOE")
    
    def test_extract_name_with_hyphen(self):
        """Test extraction of name with hyphen"""
        self.context.raw_lines = ["Nama: JOHN-DOE SMITH"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JOHN-DOE SMITH")
    
    def test_extract_name_with_multiple_spaces(self):
        """Test extraction of name with multiple spaces"""
        self.context.raw_lines = ["Nama: JOHN   DOE  SMITH"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JOHN DOE SMITH")  # Should normalize spaces


class TestNIKExtractor(unittest.TestCase):
    """Tests for the NIK extraction functionality"""
    
    def setUp(self):
        self.extractor = NIKExtractor()
        self.context = ParserContext(raw_lines=[], cleaned_lines=[], debug=True)
    
    def test_extract_nik_standard_format(self):
        """Test extraction of NIK in standard format"""
        self.context.cleaned_lines = ["NIK : 1234567890123456"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "1234567890123456")
    
    def test_extract_nik_no_space(self):
        """Test extraction of NIK with no space after colon"""
        self.context.cleaned_lines = ["NIK:1234567890123456"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "1234567890123456")
    
    def test_extract_nik_next_line(self):
        """Test extraction when NIK is on the next line"""
        self.context.cleaned_lines = ["NIK:", "1234567890123456"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "1234567890123456")
    
    def test_extract_nik_with_dashes(self):
        """Test extraction of NIK with dashes"""
        self.context.cleaned_lines = ["NIK: 1234-5678-9012-3456"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "1234567890123456")
    
    def test_extract_nik_with_spaces(self):
        """Test extraction of NIK with spaces"""
        self.context.cleaned_lines = ["NIK: 1234 5678 9012 3456"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "1234567890123456")
    
    def test_extract_nik_standalone(self):
        """Test extraction of standalone NIK without label"""
        self.context.cleaned_lines = ["1234567890123456"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "1234567890123456")
    
    def test_extract_nik_invalid_length(self):
        """Test that invalid NIK length is rejected"""
        self.context.cleaned_lines = ["NIK: 12345"]  # Too short
        result = self.extractor.extract(self.context)
        self.assertIsNone(result)

class TestAddressExtractor(unittest.TestCase):
    """Tests for the address extraction functionality"""
    
    def setUp(self):
        self.extractor = AlamatExtractor()
        self.context = ParserContext(raw_lines=[], cleaned_lines=[], debug=True)
    
    def test_extract_address_label_with_colon(self):
        """Test extraction of address with label and colon"""
        self.context.raw_lines = ["Alamat: JALAN MERDEKA NO 123"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JALAN MERDEKA NO 123")
    
    def test_extract_address_label_with_typo(self):
        """Test extraction with common OCR typos in address label"""
        self.context.raw_lines = ["Alamal: JALAN SUDIRMAN NO 45"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JALAN SUDIRMAN NO 45")
    
    def test_extract_address_on_next_line(self):
        """Test extraction of address on the line after label"""
        self.context.raw_lines = ["Alamat:", "JALAN GATOT SUBROTO NO 78"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JALAN GATOT SUBROTO NO 78")
    
    def test_extract_multi_line_address(self):
        """Test extraction of multi-line address"""
        self.context.raw_lines = [
            "Alamat:",
            "JALAN KEBON JERUK RAYA NO 10",
            "RT 003 RW 002",
            "KELURAHAN TANJUNG DUREN"
        ]
        expected = "JALAN KEBON JERUK RAYA NO 10 RT 003 RW 002 KELURAHAN TANJUNG DUREN"
        result = self.extractor.extract(self.context)
        self.assertEqual(result, expected)
    
    def test_skip_invalid_address_lines(self):
        """Test that invalid lines are skipped in multi-line addresses"""
        self.context.raw_lines = [
            "Alamat:",
            "JALAN MENTENG NO 15",
            "NIK: 1234567890123456",  # Should be skipped
            "RT 001 RW 001"
        ]
        expected = "JALAN MENTENG NO 15 RT 001 RW 001"
        result = self.extractor.extract(self.context)
        self.assertEqual(result, expected)
    
    def test_find_standalone_address(self):
        """Test finding address without a clear label"""
        self.context.raw_lines = [
            "NIK: 1234567890123456",
            "Nama: JOHN DOE",
            "JALAN MANGGA DUA NO 25",  # This looks like an address
            "RT 005 RW 003"
        ]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JALAN MANGGA DUA NO 25 RT 005 RW 003")
    
    def test_clean_address_formatting(self):
        """Test cleaning and normalizing address formatting"""
        self.context.raw_lines = [
            "Alamat:",
            "jl.  jend. sudirman  no.  kav. 29"
        ]
        expected = "JALAN JENDERAL SUDIRMAN NO KAV 29"
        result = self.extractor.extract(self.context)
        self.assertEqual(result, expected)


class TestKTPParser(unittest.TestCase):
    """Tests for the main KTP parser class"""
    
    def setUp(self):
        self.parser = KTPParser(debug=True)
    
    def test_parse_minimal_ktp(self):
        """Test parsing a minimal KTP with just NIK"""
        lines = ["NIK: 1234567890123456", "Nama: JOHN DOE"]
        result = self.parser.parse(lines)
        self.assertEqual(result["nik"], "1234567890123456")
        self.assertEqual(result["nama"], "JOHN DOE")
    
    def test_parse_empty_input(self):
        """Test parsing empty input"""
        result = self.parser.parse([])
        # Should return dict with None values for all fields
        self.assertTrue(all(v is None for v in result.values()), "All values should be None for empty input")
        self.assertIn("nik", result)
        self.assertIn("nama", result)
        self.assertIn("alamat", result)


class TestCompatibilityLayer(unittest.TestCase):
    """Tests for the compatibility layer with the original API"""
    
    def test_parse_ktp_fields_function(self):
        """Test that the module-level function works"""
        lines = ["NIK : 1234567890123456"]
        result = parse_ktp_fields(lines)
        self.assertEqual(result["nik"], "1234567890123456")

if __name__ == "__main__":
    unittest.main()
