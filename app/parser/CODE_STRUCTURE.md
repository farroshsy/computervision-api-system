# KTP Parser Code Structure

This document provides a detailed breakdown of the KTP parser's code structure and logic.

## Main Function: `parse_ktp_fields`

```python
def parse_ktp_fields(ocr_lines: List[str]) -> Dict[str, Any]
```

### Parameters
- `ocr_lines`: List of strings, where each string represents a line of text from OCR processing

### Return Value
Returns a dictionary with the following structure:
```python
{
    "nik": str,                   # 16-digit NIK (Nomor Induk Kependudukan)
    "nama": str,                  # Full name
    "tempat_lahir": str,          # Place of birth
    "tanggal_lahir": str,         # Date of birth (DD-MM-YYYY)
    "jenis_kelamin": str,         # Gender (LAKI-LAKI or PEREMPUAN)
    "gol_darah": Optional[str],   # Blood type (A, B, AB, O) or None
    "alamat": str,                # Full address
    "rt_rw": str,                 # RT/RW (Neighborhood/Community Group)
    "kelurahan": str,             # Village/Sub-district
    "kecamatan": str,             # District
    "agama": str,                 # Religion
    "status_perkawinan": str,     # Marital status
    "pekerjaan": str,             # Occupation
    "kewarganegaraan": str,       # Nationality (usually WNI for Indonesian)
    "berlaku_hingga": str         # ID expiration date
}
```

## Code Sections

### 1. NIK (ID Number) Extraction
- **Patterns Handled**:
  - Standard 16-digit number
  - Numbers with spaces/dashes
  - Numbers following "NIK" label
  - Numbers on the next line after "NIK" label

### 2. Name Extraction
- **Patterns Handled**:
  - `Nama: JOHN DOE`
  - `Nama : JOHN DOE`
  - `Kama` (on one line) + `:JOHN DOE` (on next line)
  - Unlabeled names in all caps

### 3. Birth Information
- **Place of Birth**:
  - Extracted from lines containing "Tempat/Tgl Lahir"
  - Handles various separators (/, ., ,)
  
- **Date of Birth**:
  - Multiple date formats supported (DD-MM-YYYY, DD/MM/YYYY, DD Month YYYY)
  - Handles OCR errors in dates

### 4. Gender Extraction
- Looks for "Jenis Kelamin" label
- Handles common OCR errors in the label
- Extracts gender from the same or next line

### 5. Address and Other Fields
- **Address**: Multi-line extraction with validation
- **RT/RW**: Handles various formats (e.g., "001/002", "001 002")
- **Kelurahan/Desa & Kecamatan**: Extracts from labeled fields
- **Agama**: Religion extraction with common variations
- **Status Perkawinan**: Marital status with common OCR errors
- **Pekerjaan**: Occupation extraction
- **Kewarganegaraan**: Usually "WNI" for Indonesian citizens
- **Berlaku Hingga**: ID expiration date or "SEUMUR HIDUP" for lifetime

## Debugging and Logging

### Log Files
- `ktp_parser.log`: General application logs
- `ktp_debug.log`: Detailed debug information

### Logging Levels
- `DEBUG`: Detailed debugging information
- `INFO`: Important runtime events
- `WARNING**: Non-critical issues
- `ERROR`: Critical errors

## Known Issues and Limitations

1. **Name Extraction**
   - May fail with non-standard name formats
   - Can be confused by all-caps text that isn't a name

2. **Date Parsing**
   - May misinterpret dates with OCR errors
   - Limited to common date formats

3. **Address Extraction**
   - May include or exclude parts of the address incorrectly
   - Depends on consistent label formatting

## Future Improvements

1. **Code Structure**
   - Break down into smaller, focused functions
   - Create a class-based structure
   - Add type hints for all functions

2. **Error Handling**
   - More robust error recovery
   - Better validation of extracted data

3. **Performance**
   - Optimize regex patterns
   - Add caching for common patterns

4. **Testing**
   - Add unit tests for each field extractor
   - Create test cases for edge cases
   - Add integration tests with real OCR output
