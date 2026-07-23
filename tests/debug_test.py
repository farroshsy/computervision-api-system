import unittest
import sys
import os
import re

# Add the parent directory to the path to import the parser
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.parser.ktp_parser.kelurahan_desa_extractor import KelurahanDesaExtractor
from app.models.schemas import ParserContext

class DebugTest(unittest.TestCase):
    def test_single_case(self):
        extractor = KelurahanDesaExtractor()
        context = ParserContext(
            raw_lines=["KEL/DESA: JATINEGARA"],
            cleaned_lines=["KEL/DESA: JATINEGARA"],
            debug=True
        )
        
        # Enhanced debug logging
        def debug_log(msg, **kwargs):
            print(f"[DEBUG] {msg}")
            if kwargs:
                for k, v in kwargs.items():
                    print(f"  {k}: {v}")
                    
        # Print extractor configuration
        print("\n=== Extractor Configuration ===")
        print(f"Label patterns: {extractor.label_patterns}")
        print(f"Common places: {extractor.common_places}")
        print("\n=== Test Case ===")
        print(f"Input: {context.raw_lines[0]}")
        
        # Print pattern matching attempts
        print("\n=== Pattern Matching ===")
        
        context.log_debug = debug_log
        
        # Run extraction with more detailed debugging
        print("\n=== Extraction Process ===")
        print("Trying to extract from line:", context.raw_lines[0])
        
        # Try each pattern manually
        for i, pattern in enumerate(extractor.label_patterns):
            print(f"\nTrying pattern {i+1}: {pattern[0]}")
            match = re.search(pattern[0], context.raw_lines[0], re.IGNORECASE)
            if match:
                print(f"  Match found! Groups: {match.groups()}")
                if pattern[1] > 0:
                    print(f"  Captured group: {match.group(pattern[1])}")
                else:
                    print(f"  Text after match: {context.raw_lines[0][match.end():].strip()}")
            else:
                print("  No match")
        
        # Run the actual extraction with detailed debugging
        print("\n=== Running extract() ===")
        
        # Enable detailed debug logging
        def detailed_debug(msg, **kwargs):
            print(f"[EXTRACTOR DEBUG] {msg}")
            if kwargs:
                for k, v in kwargs.items():
                    print(f"  {k}: {v}")
        
        # Save the original methods
        original_debug = context.log_debug
        original_is_fp = extractor._is_likely_false_positive
        
        # Replace methods with our debug versions
        context.log_debug = detailed_debug
        
        # Add debug to _is_likely_false_positive
        def debug_is_fp(text):
            result = original_is_fp(text)
            print(f"[IS_FP DEBUG] Checking if '{text}' is a false positive: {result}")
            if result:
                print("  Reason:")
                if not text or not text.strip():
                    print("  - Text is empty or whitespace only")
                text = text.strip()
                text_lower = text.lower()
                if len(text) < 3 or len(text) > 50:
                    print(f"  - Text length ({len(text)}) is outside valid range (3-50)")
                if re.fullmatch(r'^[\d\W_]+$', text):
                    print("  - Text contains only numbers or special characters")
                for term in extractor.skip_terms:
                    if re.search(rf'(?:^|\s){re.escape(term)}(?:\s|$)', text_lower):
                        print(f"  - Contains skip term: {term}")
                if re.search(r'\b(?:nik|nama|tempat\s+lahir|jenis\s+kelamin|gol\.?\s*darah|alamat|rt/rw|kel/desa|kecamatan|agama|pekerjaan|status|perkawinan|berlaku|hingga|kota|kabupaten|kode\s+pos|provinsi|kewarganegaraan)\b', text_lower):
                    print("  - Matches common false positive pattern")
                if re.match(r'^\d{2}[-/.]\d{2}[-/.]\d{4}$', text):
                    print("  - Looks like a date")
                if re.match(r'^\d{16,}$', text.replace(' ', '')):
                    print("  - Looks like an ID number")
                if re.search(r'\b(?:kel[\s\/.]*desa|kel[\s\/.]|kelurahan|desa)\b', text_lower):
                    print("  - Contains kelurahan/desa label")
                if text.upper() in extractor.common_places:
                    print(f"  - Is a known place: {text.upper()}")
            return result
            
        # Replace the method
        extractor._is_likely_false_positive = debug_is_fp
        
        # Run extraction
        result = extractor.extract(context)
        
        # Restore original methods
        context.log_debug = original_debug
        extractor._is_likely_false_positive = original_is_fp
        
        print(f"\n=== Final Result ===\n{result}")
        self.assertEqual(result, "JATINEGARA")

if __name__ == "__main__":
    unittest.main()
