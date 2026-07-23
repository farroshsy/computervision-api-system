# API Cookbook — copy-paste integration recipes

Base URL below assumes local Docker: `http://localhost:8000`.
All endpoints need the API key header: `X-API-Key: <your-key>`.
Interactive docs: `/docs` (Swagger UI) · machine spec: `/openapi.json`
(generate a Go/Node/PHP client with any OpenAPI generator).

**Postman**: import [`postman_collection.json`](postman_collection.json)
(31 requests incl. saved example responses for every error shape —
400/401/413/422/429), set the `baseUrl` and `apiKey` collection
variables, and every endpoint is one click away. Regenerate after route
changes with `python scripts/generate_postman.py`.

**Error contract**: every 4xx/5xx body is the same `ErrorResponse`
shape. The ones you must handle:

| code | when | your move |
|---|---|---|
| 400 | unsupported/corrupt file | fix the upload |
| 401 | missing/invalid `X-API-Key` | fix credentials |
| 413 | file too large | compress/resize client-side |
| 422 | `enforce_validation=true` and the document failed validation | treat as needs_review / retake |
| 429 | rate limit | back off and retry |

## 1. Extract fields from a document photo (type known)

```bash
curl -s -X POST "http://localhost:8000/api/v1/ocr/file" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@ktp.jpg" \
  -F "document_type=KTP"
```

## 2. Let the API detect the document type (AUTO)

```bash
curl -s -X POST "http://localhost:8000/api/v1/ocr/file" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@unknown.jpg" \
  -F "document_type=AUTO"
```

Response `meta.detection` explains the decision (per-type scores, matched
markers, confidence). `document_type: "UNKNOWN"` = don't guess → ask the
user to retake or pick the type.

## 3. Reject invalid documents instead of returning empty fields

```bash
curl -s -X POST "http://localhost:8000/api/v1/ocr/file?enforce_validation=true" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@ktp.jpg" -F "document_type=KTP"
```

HTTP 422 with `reasons` when validation fails; 200 otherwise.

## 4. Verify a document against a claimed identity

```bash
curl -s -X POST "http://localhost:8000/api/v1/ocr/verify" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@ktp.jpg" -F "document_type=KTP" \
  -F "claimed_nik=3602171001900004" \
  -F "claimed_name=PUDIN" \
  -F "claimed_dob=1990-01-10"
```

`data.verification.decision` = `match` / `no_match` (threshold via
`score_threshold`, default 0.7).

## 5. Fingerprint an image (duplicate detection — backfill step)

```bash
curl -s -X POST "http://localhost:8000/api/v1/image/fingerprint" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@archive_photo.jpg"
# -> {"fingerprint": "v1:a1b2...:c3d4...", ...}  store this in YOUR database
```

## 6. Check a new upload against stored fingerprints

```bash
curl -s -X POST "http://localhost:8000/api/v1/image/match" \
  -H "X-API-Key: $API_KEY" \
  -F "file=@new_upload.jpg" \
  -F 'candidates=["v1:a1b2...:c3d4...","v1:e5f6...:a7b8..."]'
# -> duplicate_found + ranked matches with verdicts
```

## Machine-readable reason codes (act on these, not on message strings)

| Code | Meaning | Suggested action |
|---|---|---|
| `very_low_text_content` | almost no text read | retake photo |
| `blurry_image` / `too_dark` | image quality signals | retake photo |
| `low_ocr_quality` | text read but unreliable | retake or human review |
| `missing_<type>_markers` | image likely isn't the requested type | check document type |
| `nik_pattern_not_found` | no 16-digit NIK readable | retake / review |
| `nik_dob_mismatch` | NIK-encoded birthdate ≠ printed birthdate | human review (real docs do have this!) |
| `nik_gender_mismatch` | NIK gender encoding ≠ printed gender | human review |
| `nik_region_code_unknown` / `nik_kabupaten_code_unknown` | NIK region codes not in official tables | fraud signal → review |
| `no_fields_extracted` | parsing produced nothing | retake / review |

## Operational notes

- Rate limits and upload limits are configured via `.env` (see
  `.env.example`). Responses carry `X-Processing-Time`.
- The service stores nothing: no images, no fingerprints, no PII.
- Run: `docker-compose up -d` → health check at `/api/v1/health`.
