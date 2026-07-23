import re
from typing import Dict, Any, List

def parse_sim_fields(ocr_lines: List[str]) -> Dict[str, Any]:
    """
    Parse SIM (Surat Izin Mengemudi) document fields from OCR text lines.
    Returns structured JSON with SIM fields.
    """
    # Join all lines for easier processing
    full_text = "\n".join(ocr_lines)
    
    # Initialize result dictionary with common SIM fields for Indonesian driving license
    result = {
        "nomor_sim": None,
        "nama": None,
        "tempat_tanggal_lahir": None,
        "jenis_kelamin": None,
        "alamat": None,
        "rt_rw": None,
        "kelurahan_kecamatan": None,
        "pekerjaan": None,
        "kewarganegaraan": None,
        "berlaku_hingga": None,
        "golongan_sim": None,
        "raw_text": full_text
    }
    
    # Find Nomor SIM (License Number)
    for line in ocr_lines:
        # Look for patterns like "1427-8708-000059" or "NOMOR: 1234567890"
        sim_match = re.search(r'(?:NOMOR[\s:]*)?(\d[\d\s-]{8,}\d)', line)
        if sim_match:
            result["nomor_sim"] = sim_match.group(1).strip()
            break
    
    # Find Nama (Name)
    name_patterns = [
        r'1\.?\s*([A-Z\s]+)(?=\s*\d|$)',  # Pattern for "1. NAMA"
        r'(?i)nama\s*:?\s*([A-Z\s]+)',      # Pattern for "NAMA: VALUE"
    ]
    
    for line in ocr_lines:
        for pattern in name_patterns:
            name_match = re.search(pattern, line)
            if name_match:
                result["nama"] = name_match.group(1).strip()
                break
        if result["nama"]:
            break
    
    # Find Tempat/Tanggal Lahir (Place/Date of Birth)
    for i, line in enumerate(ocr_lines):
        if re.search(r'(?:TEMPAT[/,]?\s*TGL\.?\s*LAHIR|TTL|Tgl\.?\s*Lahir)', line, re.IGNORECASE):
            # Try to find in the next line if current line is just the label
            if i + 1 < len(ocr_lines):
                result["tempat_tanggal_lahir"] = ocr_lines[i + 1].strip()
                break
    
    # Find Alamat (Address)
    address_start = None
    for i, line in enumerate(ocr_lines):
        if re.search(r'(?:ALAMAT|ALMT|Alamat)', line):
            address_start = i + 1
            break
    
    if address_start:
        address_lines = []
        for line in ocr_lines[address_start:]:
            # Stop if we hit another field
            if re.search(r'(?:RT/RW|KEL/DESA|KECAMATAN|PEKERJAAN|GOL\.?\s*DARAH)', line, re.IGNORECASE):
                break
            address_lines.append(line.strip())
        if address_lines:
            result["alamat"] = " ".join(address_lines).strip()
    
    # Find RT/RW
    for line in ocr_lines:
        rt_rw_match = re.search(r'RT[\s/]?RW[\s:]*([\d/]+)', line, re.IGNORECASE)
        if rt_rw_match:
            result["rt_rw"] = rt_rw_match.group(1)
            break
    
    # Find Kelurahan/Kecamatan
    for i, line in enumerate(ocr_lines):
        if re.search(r'(?:KEL/DESA|KEL\.?/DESA|KELURAHAN)', line, re.IGNORECASE):
            if i + 1 < len(ocr_lines):
                result["kelurahan_kecamatan"] = ocr_lines[i + 1].strip()
                break
    
    # Find Pekerjaan (Occupation)
    for i, line in enumerate(ocr_lines):
        if re.search(r'(?:PEKERJAAN|PEKERJ)', line, re.IGNORECASE):
            if i + 1 < len(ocr_lines):
                result["pekerjaan"] = ocr_lines[i + 1].strip()
                break
    
    # Find Masa Berlaku (Valid Until)
    for line in ocr_lines:
        date_match = re.search(r'(?:BERLAKU|VALID)\s*(?:UNTUK|UNTIL|HINGGA|THN|TAHUN)?[\s:]*([\d-]+)', line, re.IGNORECASE)
        if date_match:
            result["berlaku_hingga"] = date_match.group(1)
            break
    
    # Find Golongan SIM (License Class)
    for line in ocr_lines:
        golongan_match = re.search(r'(?:GOL\.?\s*DARAH|GOL\.?)[\s:]*([A-Z0-9\s-]+)', line, re.IGNORECASE)
        if golongan_match:
            result["golongan_sim"] = golongan_match.group(1).strip()
            break
    
    # Clean up empty fields
    result = {k: v for k, v in result.items() if v is not None}
    
    return result

def calculate_sim_field_accuracy(predicted: Dict[str, Any], ground_truth: Dict[str, Any]) -> float:
    """
    Calculate field-level accuracy between predicted and ground truth SIM data.
    Returns accuracy as a percentage (0-100).
    """
    if not ground_truth:
        return 0.0
    
    total_fields = len(ground_truth)
    if total_fields == 0:
        return 0.0
    
    correct_fields = 0
    
    for field, true_value in ground_truth.items():
        if field in predicted and predicted[field] == true_value:
            correct_fields += 1
    
    return (correct_fields / total_fields) * 100
