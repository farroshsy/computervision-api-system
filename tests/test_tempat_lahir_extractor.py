"""
Tests for the TempatLahirExtractor class.
"""

import unittest
import sys
from pathlib import Path

# Add the parent directory to the path so we can import the parser
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.parser.ktp_parser.tempat_lahir_extractor import TempatLahirExtractor
from app.models.schemas import ParserContext

class TestTempatLahirExtractor(unittest.TestCase):
    """Tests for the place of birth extraction functionality"""
    
    def setUp(self):
        self.extractor = TempatLahirExtractor()
        self.context = ParserContext(raw_lines=[], cleaned_lines=[], debug=True)
    
    def test_extract_standard_format(self):
        """Test extraction with standard format"""
        test_cases = [
            ("TEMPAT/LAHIR: JAKARTA", "JAKARTA"),
            ("TEMPAT : JAKARTA", "JAKARTA"),
            ("TEMPAT: JAKARTA", "JAKARTA"),
            ("TEMPAT/ TGL LAHIR: JAKARTA", "JAKARTA"),
            ("TEMPAT/LAHIR : JAKARTA", "JAKARTA"),
            ("TEMPAT/LAHIR :JAKARTA", "JAKARTA"),
            ("TEMPAT/LAHIR:JAKARTA", "JAKARTA"),
            ("TEMPAT/LAHIR JAKARTA", "JAKARTA"),
            ("TEMPAT LAHIR: JAKARTA", "JAKARTA"),
            ("TEMPAT LAHIR : JAKARTA", "JAKARTA"),
            ("TEMPAT LAHIR JAKARTA", "JAKARTA"),
            ("TEMPAT/TGL LAHIR: JAKARTA", "JAKARTA"),
            ("TEMPAT/TGL LAHIR : JAKARTA", "JAKARTA"),
            ("TEMPAT/TGL LAHIR JAKARTA", "JAKARTA"),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                self.context.raw_lines = [input_text]
                result = self.extractor.extract(self.context)
                self.assertEqual(result, expected, 
                               f"Failed for input: {input_text}. Expected: {expected}, got: {result}")
    
    def test_extract_with_ocr_errors(self):
        """Test extraction with common OCR errors"""
        test_cases = [
            ("TEMPAT/LAHIR: J4K4RT4", "JAKARTA"),
            ("TEMPAT/LAHIR: J4K4RT4 S3L4T4N", "JAKARTA SELATAN"),
            ("TEMPAT/LAHIR: JAK4RT4", "JAKARTA"),
            ("TEMPAT/LAHIR: JAK4RTA", "JAKARTA"),
            ("TEMPAT/LAHIR: JAKART4", "JAKARTA"),
            ("TEMPAT/LAHIR: J4K4RT4 SEL4T4N", "JAKARTA SELATAN"),
            ("TEMP4T/LAHIR: JAKARTA", "JAKARTA"),
            ("TEMPAT/L4H1R: JAKARTA", "JAKARTA"),
            ("TEMPAT/LAH1R: JAKARTA", "JAKARTA"),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                self.context.raw_lines = [input_text]
                result = self.extractor.extract(self.context)
                self.assertEqual(result, expected, 
                               f"Failed for input: {input_text}. Expected: {expected}, got: {result}")
    
    def test_extract_multi_line(self):
        """Test extraction when value is on the next line or split across lines"""
        test_cases = [
            (["TEMPAT/LAHIR:", "JAKARTA"], "JAKARTA"),
            (["TEMPAT/LAHIR", "JAKARTA"], "JAKARTA"),
            (["TEMPAT", "LAHIR", "JAKARTA"], "JAKARTA"),
            (["TEMPAT", "JAKARTA"], "JAKARTA"),
            (["TEMPAT/LAHIR:", "JAKARTA", "SELATAN"], "JAKARTA SELATAN"),
            (["TEMPAT/LAHIR", "JAKARTA", "SELATAN"], "JAKARTA SELATAN"),
            (["TEMPAT", "LAHIR", "JAKARTA", "SELATAN"], "JAKARTA SELATAN"),
            (["TEMPAT", "JAKARTA", "SELATAN"], "JAKARTA SELATAN"),
            (["TEMPAT/LAHIR:", "JAKARTA", "17-08-1945"], "JAKARTA"),
            (["TEMPAT/LAHIR", "JAKARTA", "17-08-1945"], "JAKARTA"),
        ]
        
        for input_lines, expected in test_cases:
            with self.subTest(input_lines=input_lines):
                self.context.raw_lines = input_lines
                result = self.extractor.extract(self.context)
                self.assertEqual(result, expected, 
                               f"Failed for input: {input_lines}. Expected: {expected}, got: {result}")
    
    def test_extract_with_date(self):
        """Test extraction when followed by date"""
        test_cases = [
            ("TEMPAT/TGL LAHIR: JAKARTA, 17-08-1945", "JAKARTA"),
            ("TEMPAT/TGL LAHIR: JAKARTA,17-08-1945", "JAKARTA"),
            ("TEMPAT/TGL LAHIR: JAKARTA 17-08-1945", "JAKARTA"),
            ("TEMPAT/TGL LAHIR JAKARTA 17-08-1945", "JAKARTA"),
            ("TEMPAT/TGL LAHIR : JAKARTA, 17-08-1945", "JAKARTA"),
            ("TEMPAT/TGL LAHIR : JAKARTA,17-08-1945", "JAKARTA"),
            ("TEMPAT/TGL LAHIR : JAKARTA 17-08-1945", "JAKARTA"),
            ("TEMPAT/TGL LAHIR : JAKARTA", "JAKARTA"),
            ("TEMPAT/TGL LAHIR : JAKARTA ", "JAKARTA"),
            ("TEMPAT/TGL LAHIR : JAKARTA SELATAN, 17-08-1945", "JAKARTA SELATAN"),
            ("TEMPAT/TGL LAHIR : JAKARTA SELATAN,17-08-1945", "JAKARTA SELATAN"),
            ("TEMPAT/TGL LAHIR : JAKARTA SELATAN 17-08-1945", "JAKARTA SELATAN"),
            ("TEMPAT/TGL LAHIR JAKARTA SELATAN 17-08-1945", "JAKARTA SELATAN"),
            ("TEMPAT/TGL LAHIR : JAKARTA SELATAN", "JAKARTA SELATAN"),
            ("TEMPAT/TGL LAHIR : JAKARTA SELATAN ", "JAKARTA SELATAN"),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(input_text=input_text):
                self.context.raw_lines = [input_text]
                result = self.extractor.extract(self.context)
                self.assertEqual(result, expected, 
                               f"Failed for input: {input_text}. Expected: {expected}, got: {result}")
    
    def test_extract_common_place(self):
        """Test extraction of common place names"""
        test_cases = [
            ("JAKARTA", "JAKARTA"),
            ("JAKARTA SELATAN", "JAKARTA SELATAN"),
            ("JAKARTA UTARA", "JAKARTA UTARA"),
            ("JAKARTA BARAT", "JAKARTA BARAT"),
            ("JAKARTA TIMUR", "JAKARTA TIMUR"),
            ("JAKARTA PUSAT", "JAKARTA PUSAT"),
            ("BANDUNG", "BANDUNG"),
            ("SURABAYA", "SURABAYA"),
            ("YOGYAKARTA", "YOGYAKARTA"),
            ("SEMARANG", "SEMARANG"),
            ("MEDAN", "MEDAN"),
            ("MAKASSAR", "MAKASSAR"),
            ("BALIKPAPAN", "BALIKPAPAN"),
            ("BANJARMASIN", "BANJARMASIN"),
        ]
        
        for input_text, expected in test_cases:
            with self.subTest(place=input_text):
                self.context.raw_lines = [input_text]
                result = self.extractor.extract(self.context)
                self.assertEqual(result, expected, 
                               f"Failed for input: {input_text}. Expected: {expected}, got: {result}")
    
    def test_skip_false_positives(self):
        """Test that false positives are skipped"""
        test_cases = [
            "JENIS KELAMIN: LAKI-LAKI",
            "STATUS PERKAWINAN: KAWIN",
            "GOLONGAN DARAH: A",
            "ALAMAT: JL. CONTOH NO. 123",
            "RT/RW: 001/002",
            "KELURAHAN: CONTOH",
            "KECAMATAN: CONTOH",
            "AGAMA: ISLAM",
            "PEKERJAAN: KARYAWAN SWASTA",
            "KEWARGANEGARAAN: WNI",
            "BERLAKU HINGGA: SEUMUR HIDUP",
        ]
        
        for input_text in test_cases:
            with self.subTest(input_text=input_text):
                self.context.raw_lines = [input_text]
                result = self.extractor.extract(self.context)
                self.assertIsNone(result, 
                               f"Failed for input: {input_text}. Expected: None, got: {result}")
    
    def test_normalize_place_name(self):
        """Test normalization of place names"""
        test_cases = [
            ("jakarta", "JAKARTA"),
            ("jakarta selatan", "JAKARTA SELATAN"),
            ("JAKARTA-selatan", "JAKARTA-SELATAN"),
            ("JAKARTA - selatan", "JAKARTA-SELATAN"),
            ("JAKARTA _ SELATAN", "JAKARTA SELATAN"),
            ("JAKARTA, SELATAN", "JAKARTA SELATAN"),
            ("JAKARTA . SELATAN", "JAKARTA SELATAN"),
            ("JAKARTA  SELATAN", "JAKARTA SELATAN"),
            ("JAKARTA   SELATAN", "JAKARTA SELATAN"),
            ("  JAKARTA SELATAN  ", "JAKARTA SELATAN"),
            ("JAKARTA-SELATAN", "JAKARTA-SELATAN"),
            ("JAKARTA - SELATAN", "JAKARTA-SELATAN"),
            ("JAKARTA _ SELATAN", "JAKARTA SELATAN"),
            ("JAKARTA, SELATAN", "JAKARTA SELATAN"),
            ("JAKARTA . SELATAN", "JAKARTA SELATAN"),
        ]
        
        for input_place, expected in test_cases:
            with self.subTest(input_place=input_place):
                self.context.raw_lines = [input_place]
                result = self.extractor.extract(self.context)
                self.assertEqual(result, expected, 
                               f"Failed for input: {input_place}. Expected: {expected}, got: {result}")

if __name__ == "__main__":
    unittest.main()
