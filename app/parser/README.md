# KTP Parser Documentation

This document provides an overview of the KTP (Indonesian ID Card) parser implementation.

## Overview

The KTP parser extracts structured data from OCR-processed text of Indonesian ID cards. It handles various formats and common OCR errors.

## File Structure

- `ktp.py`: Main parser implementation
- `ktp_parser.log`: Debug log file (generated at runtime)
- `ktp_debug.log`: Detailed debug information (generated at runtime)

## Parser Logic

### Main Function

```python
def parse_ktp_fields(ocr_lines: List[str]) -> Dict[str, Any]
```

Processes OCR text lines and returns structured KTP data.

### Field Extraction Process

1. **NIK (Nomor Induk Kependudukan)**
   - Looks for 16-digit number
   - Handles various formats and OCR errors
   - Tries multiple patterns to find the NIK

2. **Name Extraction**
   - Handles multiple formats:
     - "Nama: JOHN DOE"
     - "Nama : JOHN DOE"
     - "Kama" (on one line) + ":JOHN DOE" (on next line)
   - Validates name patterns to avoid false positives

3. **Birth Information**
   - Extracts place and date of birth
   - Handles various date formats
   - Validates date values

4. **Gender**
   - Extracts from "Jenis Kelamin" field
   - Handles common OCR errors

5. **Address and Other Fields**
   - RT/RW (Neighborhood/Community Group)
   - Kelurahan/Desa (Village/Sub-district)
   - Kecamatan (District)
   - Agama (Religion)
   - Status Perkawinan (Marital Status)
   - Pekerjaan (Occupation)
   - Kewarganegaraan (Nationality)
   - Berlaku Hingga (Valid Until)

## Debugging

### Log Files

- `ktp_parser.log`: General logging
- `ktp_debug.log`: Detailed debug information

### Log Levels

- `DEBUG`: Detailed information for debugging
- `INFO`: Important runtime events
- `WARNING`: Indicates potential issues
- `ERROR`: Errors that don't prevent the program from running

## Common Issues and Solutions

### 1. Incorrect Name Extraction
- **Symptom**: Wrong or missing name
- **Possible Causes**:
  - OCR misreads characters
  - Unusual name format
- **Solution**: Check debug logs for extraction attempts

### 2. Date Parsing Errors
- **Symptom**: Incorrect or missing birth date
- **Possible Causes**:
  - Non-standard date format
  - OCR misreads numbers/characters
- **Solution**: Verify date patterns in the debug log

## Testing

To test the parser:

1. Prepare test images of KTPs
2. Run OCR to get text lines
3. Call `parse_ktp_fields()` with the OCR output
4. Verify extracted fields against expected values

## Future Improvements

1. Add more test cases
2. Improve error handling
3. Add support for more KTP formats
4. Optimize performance for large batches
