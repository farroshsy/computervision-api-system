# Indonesian Document Verification API

A stateless OCR + verification API for Indonesian identity and vehicle
documents — KTP (e-KTP), SIM, STNK, and KIR — built for logistics
onboarding and dispatch checks (driver identity, license validity,
vehicle registration, roadworthiness) plus perceptual image
fingerprinting for duplicate-upload detection.

Design decisions, per-doctype method map, and measured accuracy:
see [docs/METHOD_BY_DOCTYPE.md](docs/METHOD_BY_DOCTYPE.md) and
[docs/RFC.md](docs/RFC.md).

## 🐳 Run the pre-built image (fastest)

Pull the image from GitHub Container Registry and start it — no build, no
source checkout needed beyond the compose file:

```bash
docker pull ghcr.io/farroshsy/computervision-api-system:latest
docker compose -f docker-compose.ghcr.yml up -d
# then open http://localhost:8000/demo
```

Quick check once it is up:

```bash
curl http://localhost:8000/health
```

> The trained YOLO field detectors (STNK plate, KTP) ship disabled in the
> public image because their weights are not bundled. The API runs on the
> rules + spatial-pairing pipeline. To enable the detectors, mount the
> `.pt` weights and set `FIELD_DETECTOR_STNK_WEIGHTS` /
> `FIELD_DETECTOR_KTP_WEIGHTS`.

## ✨ Features

- **Multiple Document Support**: Process various Indonesian document types
- **High Accuracy**: Advanced OCR with PaddleOCR backend
- **RESTful API**: Easy integration with any application
- **Authentication**: Secure API key-based authentication
- **Rate Limiting**: Protect your service from abuse
- **Monitoring**: Built-in metrics and health checks
- **Containerized**: Easy deployment with Docker

## 📋 Prerequisites

- Python 3.8+
- pip (Python package manager)
- PaddlePaddle (installed automatically)
- Tesseract OCR (for certain document types)
- Redis (for rate limiting and caching)

## 🚀 Quick Start

### 1. Clone the Repository

```bash
git clone https://github.com/farroshsy/computervision-api-system.git
cd id-document-verification-api
```

### 2. Set Up Virtual Environment (Recommended)

```bash
# Create virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
.\venv\Scripts\activate
# On Unix or MacOS:
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Environment Variables

Copy the example environment file and update the values:

```bash
cp .env.example .env
```

Edit the `.env` file with your configuration.

### 5. Run the Application

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default | Required |
|----------|-------------|---------|----------|
| `API_KEY` | Secret key for API authentication | `None` | Yes |
| `ENVIRONMENT` | Application environment (development, staging, production) | `development` | No |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL) | `INFO` | No |
| `MAX_FILE_SIZE_MB` | Maximum allowed file size in MB | `5` | No |
| `METRICS_ENABLED` | Enable/disable Prometheus metrics | `true` | No |
| `RATE_LIMITING_ENABLED` | Enable/disable rate limiting | `true` | No |
| `REDIS_URL` | Redis connection URL | `redis://localhost:6379/0` | No |
| `CORS_ORIGINS` | Allowed CORS origins (JSON array) | `["*"]` | No |

## 📚 API Documentation

### Interactive Documentation

Once the application is running, you can access the following:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI Schema**: `http://localhost:8000/openapi.json`

### Authentication

Most endpoints require an API key provided in the `X-API-Key` header:

```http
GET /api/endpoint
X-API-Key: your-api-key-here
```

### Rate Limiting

- **Global Limit**: 100 requests per minute
- **Per-Key Limit**: 60 requests per minute (when using API key)

### Endpoints

#### Process Document from File

```http
POST /api/v1/ocr/file
Content-Type: multipart/form-data
X-API-Key: your-api-key
```

**Form Data:**
- `file`: The image file to process (required)
- `document_type`: Type of document (AUTO, KTP, SIM, STNK, KIR) (required)
- `confidence_threshold`: Minimum confidence score (0.0-1.0) (optional, default: 0.7)

#### Automatic Document Type Detection (AUTO)

Pass `document_type=AUTO` and the service detects the document type from the
OCR text using a weighted marker scorer (document titles, NIK 16-digit
pattern, plate number pattern, tax-field keywords, etc.). Detection is
OCR-noise tolerant (`PR0VINSI`, `N1K` still count) and refuses to guess:
if no type reaches the minimum score with a clear margin, the response
`document_type` is `UNKNOWN`.

When AUTO is used, the response `meta.detection` block explains the decision:

```json
{
  "meta": {
    "detection": {
      "detected_type": "KTP",
      "scores": {"KTP": 10.0, "SIM": 0.0, "STNK": 0.0, "KIR": 0.0},
      "matched_markers": ["NIK", "KEWARGANEGARAAN", "PROVINSI", "NIK_16_DIGITS"],
      "confidence": 1.0
    }
  }
}
```

Works on `/api/v1/ocr/file`, `/api/v1/ocr/url`, and `/api/v1/ocr/lines`.

#### Process Document from URL

```http
POST /api/v1/ocr/url
Content-Type: application/json
X-API-Key: your-api-key

{
  "document_type": "KTP",
  "confidence_threshold": 0.7,
  "image_url": "https://example.com/document.jpg"
}
```

### Typical Fields by Document Type

- __KTP__
  - nik, nama, tempat_lahir, tanggal_lahir, jenis_kelamin, gol_darah, alamat, rt_rw, kelurahan_desa, kecamatan, agama, status_perkawinan, pekerjaan, kewarganegaraan, berlaku_hingga

- __SIM__
  - nomor_sim, nama, alamat, gol_darah, berlaku_hingga, tempat_tanggal_lahir, jenis_kelamin, kewarganegaraan, kategori

- __STNK__
  - nomor_polisi, nama_pemilik, alamat, merek, tipe, tahun, warna, nomor_rangka, nomor_mesin, masa_berlaku_pajak, bbnkb

- __KIR__
  - nomor_sertifikat, berlaku_sampai, nomor_polisi, jenis_kendaraan, merek_tipe, tahun_pembuatan, nomor_rangka, nomor_mesin

### Validation and Quality Signals

Each OCR response includes a non-breaking `data.validation` block to help callers decide if the uploaded image likely matches the requested document and whether OCR quality is sufficient:

- `is_probably_valid` (bool): Heuristic signal based on document-specific keywords and content presence.
- `reasons` (string[]): Machine-readable reasons when the heuristic flags potential issues, e.g. `very_low_text_content`, `missing_ktp_markers`, `missing_sim_markers`, `missing_stnk_markers`, `missing_kir_markers`, `low_ocr_quality`.
- `ocr_quality` (number 0.0-1.0): Lightweight proxy metric derived from OCR lines (not a model score).

Example snippet in responses:

```json
{
  "data": {
    "raw_text": ["..."],
    "fields": {"nik": {"value": "3175...", "confidence": 0.99}},
    "validation": {
      "is_probably_valid": true,
      "reasons": [],
      "ocr_quality": 0.78
    }
  }
}
```

Notes:
- This is advisory and non-blocking. You can reject uploads when `is_probably_valid` is false or log `reasons` for review.
- It complements, but does not replace, server-side content-type checks and size limits.

### Validation Enforcement (optional)

You can opt-in to reject invalid documents by passing `enforce_validation=true`.

- __/api/v1/ocr/file__ (multipart form)

  Add query param `?enforce_validation=true` to the URL when posting the form.

  Example:

  ```http
  POST /api/v1/ocr/file?enforce_validation=true
  Content-Type: multipart/form-data
  X-API-Key: your-api-key
  (form-data: file, document_type, confidence_threshold)
  ```

- __/api/v1/ocr/url__ (JSON)

  Add query param `?enforce_validation=true` to the URL.

  ```http
  POST /api/v1/ocr/url?enforce_validation=true
  Content-Type: application/json
  X-API-Key: your-api-key

  {
    "document_type": "KTP",
    "confidence_threshold": 0.7,
    "image_url": "https://example.com/document.jpg"
  }
  ```

On failure, the API returns HTTP 422 with:

```json
{
  "error": {
    "code": "validation_failed",
    "message": "Document validation failed",
    "reasons": ["missing_ktp_markers", "low_ocr_quality"],
    "ocr_quality": 0.18
  }
}
```

#### Parse Provided OCR Lines (Developer Utility)

Use this to test parsers directly without running OCR.

```http
POST /api/v1/ocr/lines
Content-Type: application/json
X-API-Key: your-api-key

{
  "document_type": "SIM",
  "lines": [
    "SURAT IZIN MENGEMUDI",
    "Nama/Name : JOHN DOE",
    "Gol. Darah : O"
  ]
}
```

Example response shape (simplified):

```json
{
  "success": true,
  "document_type": "SIM",
  "processing_time": 0.42,
  "timestamp": 1723780000.123,
  "data": {
    "raw_text": ["..."],
    "fields": {
      "nama": {"value": "JOHN DOE", "confidence": 0.95},
      "gol_darah": {"value": "O", "confidence": 0.92}
    }
  }
}
```

#### Health Check

```http
GET /health
```

#### Metrics

```http
GET /metrics
```

### Response Examples by Document Type

Below are representative response snippets. Note: `data.fields` always uses objects `{ value, confidence }`.

#### KTP

```json
{
  "success": true,
  "document_type": "KTP",
  "processing_time": 0.83,
  "timestamp": 1723780000.321,
  "data": {
    "raw_text": ["..."],
    "fields": {
      "nik": {"value": "3175095801131001", "confidence": 0.99},
      "nama": {"value": "JOHN DOE", "confidence": 0.97},
      "tempat_lahir": {"value": "JAKARTA", "confidence": 0.92},
      "tanggal_lahir": {"value": "1975-08-17", "confidence": 0.90},
      "jenis_kelamin": {"value": "LAKI-LAKI", "confidence": 0.95},
      "gol_darah": {"value": "O", "confidence": 0.94},
      "alamat": {"value": "JL. MERDEKA NO.45", "confidence": 0.93},
      "rt_rw": {"value": "002/005", "confidence": 0.91},
      "kelurahan_desa": {"value": "MENTENG", "confidence": 0.90},
      "kecamatan": {"value": "MENTENG", "confidence": 0.88},
      "agama": {"value": "ISLAM", "confidence": 0.96},
      "status_perkawinan": {"value": "KAWIN", "confidence": 0.92},
      "pekerjaan": {"value": "KARYAWAN SWASTA", "confidence": 0.86},
      "kewarganegaraan": {"value": "WNI", "confidence": 0.98},
      "berlaku_hingga": {"value": "SEUMUR HIDUP", "confidence": 0.9}
    }
  }
}
```

#### SIM

```json
{
  "success": true,
  "document_type": "SIM",
  "data": {
    "raw_text": ["..."],
    "fields": {
      "nama": {"value": "JOHN DOE", "confidence": 0.95},
      "alamat": {"value": "JL. ABC NO. 12, JAKARTA SELATAN", "confidence": 0.90},
      "gol_darah": {"value": "O", "confidence": 0.92},
      "berlaku_hingga": {"value": "2028-12-21", "confidence": 0.88},
      "nomor_sim": {"value": "1234567890", "confidence": 0.93}
    }
  }
}
```

#### STNK

```json
{
  "success": true,
  "document_type": "STNK",
  "data": {
    "raw_text": ["..."],
    "fields": {
      "nomor_polisi": {"value": "B 1234 CD", "confidence": 0.96},
      "nama_pemilik": {"value": "JOHN DOE", "confidence": 0.94},
      "alamat": {"value": "JL. XYZ NO. 5, JAKARTA", "confidence": 0.90},
      "merek": {"value": "TOYOTA", "confidence": 0.92},
      "tahun": {"value": "2020", "confidence": 0.90},
      "nomor_rangka": {"value": "MH1234ABCDE56789", "confidence": 0.89},
      "nomor_mesin": {"value": "1NZZFE123456", "confidence": 0.88},
      "masa_berlaku_pajak": {"value": "2026-05-30", "confidence": 0.87}
    }
  }
}
```

#### KIR

```json
{
  "success": true,
  "document_type": "KIR",
  "data": {
    "raw_text": ["..."],
    "fields": {
      "nomor_sertifikat": {"value": "1234567", "confidence": 0.93},
      "berlaku_sampai": {"value": "2025-09-15", "confidence": 0.91},
      "nomor_polisi": {"value": "B 1234 CD", "confidence": 0.90}
    }
  }
}
```

## 🧪 Running Tests

```bash
# Install test dependencies
pip install -r requirements-test.txt

# Run tests
pytest
```

## 🛠️ Utilities

### Dump OCR Lines from Images

Generate text line dumps from images for evaluation. Lines are written under `newdata/result/<TYPE>/lines/` mirroring input subpaths.

```bash
python scripts/dump_ocr_lines.py --type KTP --input-dir newdata/input/KTP --output-dir newdata/result
```

### Run Parser on a Text File of Lines

Feed a `.txt` file (one OCR line per line) into a specific parser and print the JSON result.

```bash
# KTP
python scripts/run_document_parser.py --type KTP --input newdata/input/KTP/sample_lines.txt

# SIM / STNK / KIR
python scripts/run_document_parser.py --type SIM --input newdata/input/SIM/sample_lines.txt
```

## 🐳 Docker Deployment

### Build the Docker Image

```bash
docker build -t ocr-api .
```

### Run with Docker Compose

```bash
docker-compose up -d
```

## ❗ Troubleshooting

- **Port 8000 conflict**: If a local Uvicorn or other process is bound to `127.0.0.1:8000`, smoke tests may hit that process instead of the Docker container.
  - Stop the local process or remap Docker to a different host port (e.g., `8001:8000`) and target `http://127.0.0.1:8001`.
  - Check listeners on Windows:
    ```powershell
    netstat -ano | findstr :8000
    ```
- **Smoke test target overrides**: `scripts/smoke_ocr.ps1` accepts overrides via parameters or environment variables.
  - Parameters: `-ApiBase`, `-ApiKey`
  - Environment variables: `OCR_API_BASE`, `OCR_API_KEY`
  - Examples:
    ```powershell
    # Use alternate port
    $env:OCR_API_BASE = 'http://127.0.0.1:8001'
    powershell -ExecutionPolicy Bypass -File scripts/smoke_ocr.ps1

    # Or pass explicitly
    powershell -ExecutionPolicy Bypass -File scripts/smoke_ocr.ps1 -ApiBase 'http://127.0.0.1:8001'
    ```

## 🤝 Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR)
- [FastAPI](https://fastapi.tiangolo.com/)
- [PaddlePaddle](https://www.paddlepaddle.org.cn/)

---

<div align="center">
  Indonesian Document Verification API
</div>
