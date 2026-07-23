"""
Test cases for the RtRwExtractor class in the KTP parser.
"""
import unittest
import logging
import sys
import os

# Add the parent directory to the path so we can import the parser
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.parser.ktp_parser.rt_rw_extractor import RtRwExtractor
from app.models.schemas import ParserContext

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TestRtRwExtractor(unittest.TestCase):    
    def setUp(self):
        """Set up test fixtures."""
        self.extractor = RtRwExtractor()
        
    def create_context(self, lines):
        """Helper method to create a parser context with test data."""
        return ParserContext(
            raw_lines=lines,
            cleaned_lines=lines,  # For simplicity, use raw lines as cleaned lines
            debug=True
        )
    
    def test_standard_format(self):
        """Test standard RT/RW format."""
        lines = [
            "RT/RW : 001/002",
            "NIK : 1234567890123456"
        ]
        context = self.create_context(lines)
        result = self.extractor.extract(context)
        self.assertEqual(result, "001/002")
    
    def test_with_colon(self):
        """Test RT/RW with colon separator."""
        lines = ["RT/RW: 003/004"]
        context = self.create_context(lines)
        result = self.extractor.extract(context)
        self.assertEqual(result, "003/004")
    
    def test_with_dot_separator(self):
        """Test RT/RW with dot separator."""
        lines = ["RT.RW : 005/006"]
        context = self.create_context(lines)
        result = self.extractor.extract(context)
        self.assertEqual(result, "005/006")
    
    def test_with_space_separator(self):
        """Test RT RW with space separator."""
        lines = ["RT RW : 007/008"]
        context = self.create_context(lines)
        result = self.extractor.extract(context)
        self.assertEqual(result, "007/008")
    
    def test_with_slash_separator(self):
        """Test RT/RW with slash separator."""
        lines = ["RT/RW: 009/010"]
        context = self.create_context(lines)
        result = self.extractor.extract(context)
        self.assertEqual(result, "009/010")
    
    def test_with_ocr_errors(self):
        """Test RT/RW with common OCR errors."""
        test_cases = [
            ("RT-RW : 011/012", "011/012"),
            ("RT.RW : 013/014", "013/014"),
            ("RT RW : 015/016", "015/016"),
            ("RT-RW:017/018", "017/018"),
            ("RT.RW:019/020", "019/020"),
            ("RT RW 021/022", "021/022"),
        ]
        
        for input_line, expected in test_cases:
            with self.subTest(input_line=input_line, expected=expected):
                context = self.create_context([input_line])
                result = self.extractor.extract(context)
                self.assertEqual(result, expected)
    
    def test_with_extra_spaces(self):
        """Test RT/RW with extra spaces."""
        lines = ["RT  /  RW   :   023 / 024  "]
        context = self.create_context(lines)
        result = self.extractor.extract(context)
        self.assertEqual(result, "023/024")
    
    def test_without_label(self):
        """Test RT/RW value without a label."""
        lines = ["025/026"]
        context = self.create_context(lines)
        result = self.extractor.extract(context)
        self.assertEqual(result, "025/026")
    
    def test_invalid_format(self):
        """Test invalid RT/RW formats."""
        test_cases = [
            "RT/RW: 123",           # Missing RW part
            "RT/RW: abc/def",       # Non-numeric
            "RT/RW: 001/002/003",  # Too many parts
            "RT/RW: 1/2",           # Too few digits
            "RT/RW: 12345/67890",   # Too many digits
        ]
        
        for input_line in test_cases:
            with self.subTest(input_line=input_line):
                context = self.create_context([input_line])
                result = self.extractor.extract(context)
                self.assertIsNone(result, f"Expected None for input: {input_line}")

if __name__ == "__main__":
    unittest.main()
