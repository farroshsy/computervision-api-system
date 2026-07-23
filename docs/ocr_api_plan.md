# OCR API Delivery Plan and Guardrails

Last updated: 2025-08-17T16:44:40+07:00

## Objectives
- Remove python-magic dependency (done), ensure robust Pillow-based validation.
- Achieve acceptable OCR on real docs (KTP/SIM/STNK/KIR).
- Strictly validate/reject non-doc or mismatched uploads when enforce_validation=true.
- Provide verification flow (no external DB yet) with match score/decision.
- Make API production-ready: metrics, perf hardening, simple load test.

## Scope (No Out-of-Scope Work Until OCR Is Acceptable)
- In scope now: OCR quality, document validation, `/ocr/file`, `/ocr/verify`, metrics, perf tuning.
- Deferred: Full DB integration, pytest suites inside container, complex classifiers.

## Phased Plan
1) Baseline OCR & Validation (Now)
- Run smoke tests on known good images via `scripts/smoke_ocr.ps1`.
- Use `enforce_validation=true` to ensure non-docs/mismatches reject.
- Tune minimal knobs if weak: PPOCR_LANG (unsupported values like 'multi' are coerced to 'latin'; fallback to 'en' if init fails), preprocessing thresholds, confidence cutoffs.

2) Verify Endpoint (App-side) (Now)
- `/api/v1/ocr/verify` returns `verification` with score/decision.
- Scoring: KTP uses exact NIK/DOB, name token similarity; others use name similarity.

3) Performance & Observability (Next)
- Warm model at startup; add request timing and `X-Processing-Time` header.
- Limit image size and dimensions; threadpool tuning; optional multi-worker.
- Simple load test to capture P50/P95.

4) Integration Hooks (Later)
- Pluggable identity provider client (REST stub) for future real DB.

## Acceptance Criteria (Phase 1)
- Good KTP/SIM/STNK/KIR samples: key fields extracted and validation passes with minimal reasons.
- Random/mismatched images: rejected with 422 when `enforce_validation=true`.
- Average OCR confidence/logs show reasonable quality (line count and avg conf reported).

## Commands
- Smoke tests: `powershell -ExecutionPolicy Bypass -File scripts/smoke_ocr.ps1 -EnforceValidation`
- Verify API example (PowerShell):
```
$base="http://127.0.0.1:8000"; $key="test-api-key"
Invoke-RestMethod -Method Post -Uri "$base/api/v1/ocr/verify" -Headers @{"X-API-Key"=$key} -Form @{
  file=Get-Item "newdata/input/KTP/ID_good.jpeg"; document_type="KTP";
  claimed_nik="3175095801131001"; claimed_name="JOHN DOE"; claimed_dob="1990-01-01"; score_threshold="0.75"
} | ConvertTo-Json -Depth 6
```

## Guardrails
- Do not divert into pytest/container test infra until OCR quality and validation meet acceptance.
- Keep Docker restarts minimal; avoid port conflicts (prefer 8000 or remap to 8001 if needed). Kill stray host `python3.10.exe` binding 127.0.0.1:8000 when running containerized tests.
- Maintain Pillow-only MIME detection.

## Current Notes
- PaddleOCR language handling: if `PPOCR_LANG` is 'multi' or unsupported, we coerce to `latin` for 2.7.x; on any init error we fallback to `en`.
  - Enhanced preprocessing with alt pipeline and fallback to original image when no text detected.
  - Relaxed validation markers for SIM/STNK/KIR and KTP acceptance when parsed/schema NIK is present.

- Deps pinned for stability (CPU): `paddlepaddle==2.6.1`, `paddleocr==2.7.0.3`, `numpy==1.26.4`.
- Timeouts: per-attempt OCR timeout baseline 20s; KTP 22s; retries tuned by doc type.
- Debugging: `PPOCR_DEBUG_SAVE=1` to persist intermediate preprocessed/rotated images; `PPOCR_DEBUG_DIR` to override destination (default `debug_preproc/`). Cleanup is skipped when debug-save is enabled.

## Recent OCR Robustness Updates
- KTP: Increased per-attempt timeout (22s) and retries (3). Added KTP-specific fallback2 (HSV V, CLAHE, unsharp, OTSU, light open).
- SIM: Added aggressive fallback2 (HSV V, strong CLAHE, unsharp, OTSU, close→open, upscale). Added denoise-alt branch (bilateral + NLM + adaptive + light open) and micro-rotation sweep (-3..+3°, skip 0) with quick-score selection.
- STNK/KIR: Tuned fallback2 to upscale more (~2.1x), stronger CLAHE, and close→open morphology.
- KIR: Added fallback3 pipeline (top-hat + black-hat enhancement, strong CLAHE + unsharp, OTSU ∨ Adaptive, close→open, upscale to ~1800px) triggered when STNK/KIR fallback2 remains empty/low.
- Per-stage logging: quick-score lines/avg for primary, alt, SIM/STNK/KIR fallback2, KIR fallback3; final log includes `stage_used` and `doc_type`. Temp files are cleaned up.

## Observations from Latest Local Runs
- KTP: Stable, rich text, high OCR quality on both samples.
- SIM: Very hard sample (`DL_bad.jpg`) still produces low-quality lines; rotation sweep and denoise-alt did not significantly improve it. Debug-save enabled for inspection.
- STNK/KIR: Low-text cases now trigger fallback2 based on quick-score; KIR has an additional fallback3 if still low/empty.

## Next Immediate Engineering Tasks
1) Run Docker smoke tests via `scripts/smoke_ocr.ps1` ensuring no host port conflicts; confirm endpoints and auth behave as expected.
2) Iterate SIM: consider Sauvola/Bradley threshold branch and slightly wider rotation if needed (-4..+4) based on debug images.
3) Optional GPU enablement later: install `paddlepaddle-gpu` that matches local CUDA; verify `paddle.is_compiled_with_cuda()`; benchmark vs CPU.
4) Proceed to light load test only after single-sample runs are acceptable.

## Environment Flags Summary
- `PPOCR_LANG`: coerces unsupported (e.g., 'multi') to 'latin'; falls back to 'en' on init error.
- `PPOCR_USE_GPU`: '1' to attempt GPU (disabled by default).
- `PPOCR_DEBUG_SAVE`: '1' to persist intermediate images; `PPOCR_DEBUG_DIR` to set output directory.
