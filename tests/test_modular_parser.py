"""
Tests for the modular KTP parser.
This test file is designed to run without loading the main application.
"""

import unittest
import sys
from pathlib import Path

# Add the parent directory to the path so we can import the parser
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import only the modular components we need
from app.parser.ktp_parser.ktp_parser import KTPParser, ParserContext
from app.parser.ktp_parser import NameExtractor, NIKExtractor, AlamatExtractor

class TestModularNameExtractor(unittest.TestCase):
    """Tests for the name extraction functionality using the modular extractor."""
    
    def setUp(self):
        self.extractor = NameExtractor()
        self.context = ParserContext(raw_lines=[], cleaned_lines=[], debug=True)
    
    def test_extract_name_standard_format(self):
        """Test extraction of name in standard format."""
        self.context.raw_lines = ["Nama : JOHN DOE"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JOHN DOE")
    
    def test_extract_name_with_ocr_errors(self):
        """Test extraction of name with common OCR errors."""
        self.context.raw_lines = ["Nama : J0HN D0E"]  # Common OCR errors (0 instead of O)
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "JOHN DOE")

class TestModularNIKExtractor(unittest.TestCase):
    """Tests for the NIK extraction functionality using the modular extractor."""
    
    def setUp(self):
        self.extractor = NIKExtractor()
        self.context = ParserContext(raw_lines=[], cleaned_lines=[], debug=True)
    
    def test_extract_nik_standard_format(self):
        """Test extraction of NIK in standard format."""
        self.context.raw_lines = ["NIK : 3273010112340001"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "3273010112340001")
    
    def test_extract_nik_with_spaces(self):
        """Test extraction of NIK with spaces."""
        self.context.raw_lines = ["NIK : 3273 0101 1234 0001"]
        result = self.extractor.extract(self.context)
        self.assertEqual(result, "3273010112340001")

class TestModularKTPParser(unittest.TestCase):
    """Tests for the main KTP parser class using the modular implementation."""
    
    def setUp(self):
        self.parser = KTPParser()
        self.sample_ktp = [
            "PROVINSI JAWA BARAT",
            "KOTA BANDUNG",
            "NIK : 3273010112340001",
            "Nama : JOHN DOE",
            "Tempat/Tgl Lahir : BANDUNG, 01-01-1990",
            "Jenis Kelamin : LAKI-LAKI",
            "Alamat : JL. CONTOH NO. 123",
            "RT/RW : 001/002",
            "Kel/Desa : CIBEUNYING KIDUL",
            "Kecamatan : REGOL",
            "Agama : ISLAM",
            "Status Kawin : BELUM KAWIN",
            "Pekerjaan : KARYAWAN SWASTA",
            "Kewarganegaraan : WNI",
            "Berlaku Hingga : SEUMUR HIDUP"
        ]
    
    def test_parse_complete_ktp(self):
        """Test parsing a complete KTP."""
        result = self.parser.parse(self.sample_ktp)
        self.assertEqual(result.get('nik'), '3273010112340001')
        self.assertEqual(result.get('nama'), 'JOHN DOE')
        self.assertEqual(result.get('tempat_lahir'), 'BANDUNG')
        self.assertEqual(result.get('alamat'), 'JL. CONTOH NO. 123')
    
    def test_parse_empty_input(self):
        """Test parsing with empty input."""
        result = self.parser.parse([])
        self.assertEqual(result, {})

if __name__ == "__main__":
    unittest.main()
