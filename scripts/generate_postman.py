"""Generate an importable Postman collection from the live OpenAPI spec.

Regenerate after route changes:
    python scripts/generate_postman.py
Writes docs/postman_collection.json (Postman Collection v2.1). Import it
in Postman, set the `baseUrl` and `apiKey` collection variables, done.

Success AND error examples (400/401/413/422/429) are attached to the
core endpoints so integrators see every failure shape without having to
provoke it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE = "{{baseUrl}}"

# Curated example responses per (METHOD, path). Every value is synthetic.
_ERR = {
    "unsupported_type": (400, {"success": False, "error": "Unsupported file type: application/zip",
                               "detail": "Allowed: image/jpeg, image/png, image/webp, application/pdf"}),
    "undecodable": (400, {"success": False, "error": "Could not decode image",
                          "detail": "File is corrupt or not an image"}),
    "bad_key": (401, {"success": False, "error": "Invalid or missing API key"}),
    "too_large": (413, {"success": False, "error": "File too large",
                        "detail": "Maximum upload size exceeded"}),
    "enforce_failed": (422, {"success": False, "error": "Validation failed",
                             "detail": "enforce_validation=true and document failed validation",
                             "reasons": ["missing_ktp_markers", "nik_pattern_not_found"]}),
    "rate_limited": (429, {"error": "Rate limit exceeded: 30 per 1 minute"}),
}

EXAMPLES = {
    ("POST", "/api/v1/ocr/file"): {
        "success": (200, {
            "success": True, "document_type": "KTP", "processing_time": 3.42,
            "timestamp": "2026-07-12T10:00:00Z",
            "data": {
                "fields": {
                    "nik": {"value": "3174041708900001", "confidence": 0.98,
                            "provenance": {"method": "spatial_pairing"}},
                    "nama": {"value": "BUDI SANTOSO", "confidence": 0.95},
                    "tanggal_lahir": {"value": "17-08-1990", "confidence": 0.75,
                                      "provenance": {"method": "derived_from_nik"}},
                },
                "validation": {
                    "is_probably_valid": False,
                    "reasons": ["grayscale_possible_photocopy"],
                    "ocr_quality": 0.91,
                    "image_quality": {"blur_score": 950.2, "brightness": 0.82,
                                      "is_blurry": False, "is_too_dark": False,
                                      "short_side": 899, "saturation": 1.2},
                },
            },
            "meta": {"detection": {"doc_type": "KTP",
                                   "scores": {"KTP": 11.0, "SIM": 2.0, "STNK": 0.0, "KIR": 0.0},
                                   "confidence": 0.87}},
        }),
        "wrong_slot": (200, {
            "success": True, "document_type": "KTP",
            "data": {"fields": {},
                     "validation": {"is_probably_valid": False,
                                    "reasons": ["document_type_mismatch", "missing_card_header"],
                                    "detected_type": "SIM", "ocr_quality": 0.88}},
            "_note": "declared KTP but the photo is a SIM — re-request the right document",
        }),
        "errors": ["unsupported_type", "undecodable", "bad_key", "too_large", "enforce_failed",
                   "rate_limited"],
    },
    ("POST", "/api/v1/verify/document"): {
        "success": (200, {
            "success": True, "document_type": "SIM", "decision": "no_match",
            "checks": [
                {"field": "sim_number", "claimed": "1427-8708-000059",
                 "extracted": "1427-8708-000059", "status": "matched"},
                {"field": "name", "claimed": "JAKA SALMAN",
                 "extracted": "JAKASALMAN", "status": "matched"},
            ],
            "reasons": ["sim_expired"],
            "extracted": {"sim_number": "1427-8708-000059", "name": "JAKASALMAN"},
            "lines_read": 24,
        }),
        "wrong_slot": (200, {
            "success": True, "document_type": "SIM", "decision": "needs_review",
            "checks": [], "reasons": ["wrong_document_type"], "detected_type": "KTP",
            "extracted": {}, "lines_read": 31,
            "_note": "photo in the wrong slot is a re-request, never a match or a reject",
        }),
        "errors": ["unsupported_type", "bad_key", "too_large", "rate_limited"],
    },
    ("POST", "/api/v1/verify/trip"): {
        "success": (200, {
            "success": True, "decision": "NO_GO",
            "documents": {
                "SIM": {"decision": "no_match", "reasons": ["sim_expired"],
                        "checks": [], "extracted": {"sim_number": "1427-8708-000059"}},
                "STNK": {"decision": "match", "reasons": [], "checks": [],
                         "extracted": {"nomor_polisi": "B 9437 SRU"}},
                "KIR": {"decision": "match", "reasons": [], "checks": [],
                        "extracted": {"vehicle_id": "B 9437 SRU", "valid_until": "2026-01-01"}},
            },
        }),
        "errors": ["unsupported_type", "bad_key", "rate_limited"],
    },
    ("POST", "/api/v1/image/fingerprint"): {
        "success": (200, {"success": True, "fingerprint": "v1:9f86d081884c7d65:a3b1c2d4e5f60718",
                          "algorithm": "dhash+phash-64"}),
        "errors": ["unsupported_type", "bad_key"],
    },
    ("POST", "/api/v1/image/match"): {
        "success": (200, {"success": True, "duplicate_found": True,
                          "results": [{"fingerprint": "v1:9f86d081884c7d65:a3b1c2d4e5f60718",
                                       "hamming": 3, "verdict": "duplicate"}]}),
        "errors": ["bad_key"],
    },
    ("POST", "/api/v1/logistics/container"): {
        "success": (200, {"success": True,
                          "results": [{"container_number": "CSQU3054383", "valid": True,
                                       "check_digit": 3, "owner_code": "CSQ",
                                       "category": "U"}]}),
        "errors": ["bad_key"],
    },
}


def _example_response(name, status_code, body, request):
    return {
        "name": name,
        "originalRequest": request,
        "status": "OK" if status_code == 200 else "Error",
        "code": status_code,
        "header": [{"key": "Content-Type", "value": "application/json"}],
        "body": json.dumps(body, indent=2, ensure_ascii=False),
    }


def _form_body(schema_props, required):
    data = []
    for key, prop in (schema_props or {}).items():
        is_file = prop.get("format") == "binary"
        entry = {"key": key, "type": "file" if is_file else "text"}
        if not is_file:
            entry["value"] = prop.get("description", "") and "" or ""
        entry["description"] = (prop.get("description") or "") + (
            " (required)" if key in (required or []) else " (optional)")
        data.append(entry)
    return {"mode": "formdata", "formdata": data}


def main() -> int:
    from app.main import app
    spec = app.openapi()

    folders = {}
    for path, methods in sorted(spec.get("paths", {}).items()):
        for method, op in methods.items():
            method_up = method.upper()
            if method_up not in ("GET", "POST", "PUT", "DELETE"):
                continue
            tag = (op.get("tags") or ["other"])[0]
            request = {
                "method": method_up,
                "header": [{"key": "X-API-Key", "value": "{{apiKey}}"}],
                "url": {"raw": BASE + path,
                        "host": [BASE], "path": [p for p in path.strip("/").split("/")]},
                "description": (op.get("summary") or "") + "\n\n" + (op.get("description") or ""),
            }
            body_spec = ((op.get("requestBody") or {}).get("content") or {})
            if "multipart/form-data" in body_spec:
                schema = body_spec["multipart/form-data"].get("schema") or {}
                request["body"] = _form_body(schema.get("properties"), schema.get("required"))
            elif "application/json" in body_spec:
                request["body"] = {"mode": "raw", "raw": "{}",
                                   "options": {"raw": {"language": "json"}}}

            responses = []
            curated = EXAMPLES.get((method_up, path))
            if curated:
                for key, val in curated.items():
                    if key == "errors":
                        continue
                    code, body = val
                    responses.append(_example_response(f"{code} {key}", code, body, request))
                for err in curated.get("errors", []):
                    code, body = _ERR[err]
                    responses.append(_example_response(f"{code} {err}", code, body, request))

            folders.setdefault(tag, []).append({
                "name": f"{method_up} {path}",
                "request": request,
                "response": responses,
            })

    collection = {
        "info": {
            "name": "Indonesian Document Verification API",
            "description": "Driver & vehicle document OCR + verification (KTP/SIM/STNK/KIR).\n"
                           "Set collection variables `baseUrl` and `apiKey`.\n"
                           "Every 4xx/5xx body follows the same ErrorResponse shape.",
            "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
        },
        "variable": [
            {"key": "baseUrl", "value": "http://localhost:8000"},
            {"key": "apiKey", "value": "your-api-key"},
        ],
        "item": [{"name": tag, "item": items} for tag, items in sorted(folders.items())],
    }
    out = Path(__file__).resolve().parent.parent / "docs" / "postman_collection.json"
    out.write_text(json.dumps(collection, indent=2, ensure_ascii=False), encoding="utf-8")
    n_req = sum(len(items) for items in folders.values())
    n_resp = sum(len(i["response"]) for items in folders.values() for i in items)
    print(f"{out} — {n_req} requests in {len(folders)} folders, {n_resp} example responses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
