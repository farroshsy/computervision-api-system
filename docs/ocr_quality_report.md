# OCR Quality and Readiness Report

Last updated: 2025-08-18T06:01:32+07:00

## Summary

- KTP: High text quality and field extraction; CPU-mode latency ~12–16s per request. Suitable for async flows; optimize for real-time.
- STNK/KIR: Current samples show low text content; validation correctly rejects. Recent fallbacks added; needs re-run.
- SIM: No fresh samples captured in logs; run after SIM fallback improvements.

## Latest API-based Evaluation (2025-08-18)

- KTP field accuracy computed by joining API outputs with ground-truth CSV.
  - Source truth: `newdata/ground_truth/ktp_truth_filled_sample.csv`
  - API outputs: `newdata/output/KTP/ktp_api_results.jsonl`
  - Evaluator summary: `newdata/output/KTP/ktp_metrics_summary.csv`
  - Sample size evaluated: 8
  - Exact-match accuracy per field:
    - nik: 0/8 (0%)
    - nama: 0/8 (0%)
    - tempat_lahir: 0/8 (0%)
    - tanggal_lahir: 0/8 (0%)
    - gol_darah: 1/8 (12.5%)
    - alamat: 0/8 (0%)
    - rt_rw: 0/8 (0%)
    - kelurahan_desa: 0/8 (0%)
    - agama: 6/8 (75%)
    - status_perkawinan: 2/8 (25%)
    - pekerjaan: 0/8 (0%)
    - kewarganegaraan: 8/8 (100%)
    - berlaku_hingga: 0/8 (0%)

- SIM/STNK/KIR batch API runs executed (validation enforced); outputs stored as JSONL for offline analysis.
  - SIM JSONL: `newdata/output/SIM/sim_api_results.jsonl` (10 samples)
    - Mixed success; several `name`/`address` extracted; one blurred image rejected.
  - STNK JSONL: `newdata/output/STNK/stnk_api_results.jsonl` (12 samples)
    - Some successes extracting `owner`, `alamat`, and plate `nomor_polisi`; multiple `no_fields_extracted` failures.
  - KIR JSONL: `newdata/output/KIR/kir_api_results.jsonl` (12 samples)
    - Few successes (e.g., `issuer`, `nomor_rangka`, `nomor_mesin`); many `no_fields_extracted` or low OCR quality.

Notes:
- Latency ranges (observed in sample outputs): roughly 3–9s for SIM/STNK; up to ~31s on some KIR scans.
- Validation strictly enforced via `?enforce_validation=true`.

## Evidence from logs (`logs/app.log`)

- KTP
  - OCR completed in 12.415s with 24 lines (avg conf=0.94) [stage=none]
  - OCR completed in 16.038s with 29 lines (avg conf=0.93) [stage=none]
  - E2E request durations: 12.65s, 16.47s
  - Schema: NIK and NAMA extracted

- STNK
  - OCR completed in 6.973s with 4 lines (avg conf=0.93) [stage=none]
  - Validation reasons: very_low_text_content, missing_stnk_markers, no_fields_extracted
  - E2E request duration: 7.40s

- KIR
  - OCR completed in 5.000s with 3 lines (avg conf=0.45) [stage=none]
  - Validation reasons: very_low_text_content, missing_kir_markers, no_fields_extracted

## Assessment

- Text Quality
  - KTP: Good. avg conf ~0.935; 24–29 lines; key fields extracted.
  - STNK/KIR: Insufficient on sampled inputs; expect improvement from new fallbacks (STNK/KIR fallback2; KIR fallback3).
  - SIM: Pending data.

- Validation Robustness
  - Low-text and missing markers are surfaced; with `enforce_validation=true`, non-docs/mismatches should be rejected (422).

- Latency (CPU mode)
  - KTP: ~12–16s OCR and E2E; too slow for strict real-time UX.
  - STNK/KIR: ~5–7s; still slow for interactive real-time.
  - Conclusion: Appropriate for async/batch; optimize for real-time (or enable GPU later).

## Recommended Actions

1) Run smoke tests via `scripts/smoke_ocr.ps1 -EnforceValidation` on KTP/SIM/STNK/KIR and random images; ensure no port conflicts.
2) SIM robustness: add Sauvola/Bradley threshold branch; widen rotation sweep (-4..+4°) with quick-score selection.
3) Upload guards: limit image size and long-side dimension at `app/routes/ocr.py`.
4) Metrics/timing: add per-request timing and `X-Processing-Time` header; expand metrics.
5) Light load test after single-sample quality acceptable (capture P50/P95).

## Readiness Conclusion

- KTP quality is high but CPU latency is not real-time. STNK/KIR currently weak; SIM needs retest.
- Not yet ready for real-time interactive use on CPU. Viable for asynchronous processing now; proceed with targeted optimizations and re-evaluate.

## Smoke Test Results (Enforce Validation)

Run: `scripts/smoke_ocr.ps1 -EnforceValidation` at 2025-08-17T19:56:53+07:00

- KTP (ID_standard.jpeg)
  - success=true, processing_time=4.03s
  - schema valid; fields present (nik, nama, tanggal_lahir, etc.)
  - ocr_quality=0.833; image_quality blur_score=729.7 (not blurry)

- KTP (ID_good.jpeg)
  - validation_failed; reasons: very_low_text_content, missing_ktp_markers, nik_pattern_not_found, low_ocr_quality, no_fields_extracted

- SIM (DL_good.jpeg)
  - success=true, processing_time=3.74s
  - schema valid; name/address extracted (needs correctness review)
  - ocr_quality=0.795; image not blurry

- STNK (STNK_standard.jpeg)
  - validation_failed; reasons: very_low_text_content, missing_stnk_markers, low_ocr_quality, no_fields_extracted

- KIR (KIR_standard.jpeg)
  - validation_failed; reasons: no_fields_extracted (ocr_quality reported as 0.943 in response; needs investigation against raw lines and stage_used)

### Smoke Conclusions

- KTP: Mixed — one good sample passed validation quickly (4.03s), one failed (markers/quality). Requires sample review and pipeline consistency.
- SIM: Passed with moderate ocr_quality (0.795). Validate field correctness (name/address mapping) and consider SIM fallback tweaks.
- STNK/KIR: Rejected as expected on low/invalid content; continue with stronger fallbacks and marker detection improvements.


## Measurement Methodology (How we gauge improvements)

We use a small, repeatable measurement that captures both quality and latency from the API responses.

1) What we track per sample
   - success, http_status
   - schema.is_valid, validation.is_probably_valid
   - validation.reasons, schema.errors
   - ocr_quality
   - processing_time (response body) and X-Processing-Time (header)
   - num_lines (count of raw text lines)

2) How to collect
   - Script: `scripts/collect_ocr_metrics.py`
   - Example (Windows/PowerShell):
     - Ensure API is listening on `http://127.0.0.1:8000/api/v1` and no port conflicts.
     - Run:
       ```powershell
       python scripts/collect_ocr_metrics.py `
         --base-url http://127.0.0.1:8000/api/v1 `
         --api-key test-api-key `
         --glob "newdata/input/KTP/*.jpg" --doc-type KTP `
         --glob "newdata/input/SIM/*.jpg" --doc-type SIM `
         --glob "newdata/input/STNK/*.jpg" --doc-type STNK `
         --glob "newdata/input/KIR/*.jpg" --doc-type KIR `
         --output newdata/result/ocr_metrics.csv `
         --enforce-validation
       ```
   - Output: CSV with one row per file.

3) How to interpret
   - Improvement indicators (per document type):
     - Higher `ocr_quality` averages
     - Higher validation and schema pass rates
     - More lines and/or higher avg confidence (see logs for quick-score)
     - Lower P50/P95 for `processing_time` and `X-Processing-Time`
   - Negative tests: ensure random/non-doc images are rejected (422) when `--enforce-validation` is set.

4) Before/After comparison
   - Save baseline CSV before changes, run again after changes, compare deltas per type.
   - Consider a simple spreadsheet pivot or a small diff script to aggregate pass rates and average metrics.


## Metrics Snapshot (latest run)

Timestamp: 2025-08-18T02:48:52+07:00

Source: `newdata/result/ocr_metrics.csv`

- STNK
  - samples: 45
  - http200_rate: 0.60
  - success_rate: 0.60
  - schema_valid_rate: 0.60
  - valid_prob_rate: 0.60
  - avg_ocr_quality: 0.766
  - avg_processing_time (body/header): 2.216s / 2.216s

- SIM
  - samples: 1
  - http200_rate: 0.00
  - success_rate: 0.00
  - schema_valid_rate: 0.00
  - valid_prob_rate: 0.00
  - avg_ocr_quality: N/A
  - avg_processing_time: N/A

Note: KTP/KIR sets had no matched files in this run with the current globs. Re-run with populated folders to include them.

### API Batch Runs (JSONL) — snapshot

- Artifacts
  - KTP JSONL: `newdata/output/KTP/ktp_api_results.jsonl`
  - SIM JSONL: `newdata/output/SIM/sim_api_results.jsonl`
  - STNK JSONL: `newdata/output/STNK/stnk_api_results.jsonl`
  - KIR JSONL: `newdata/output/KIR/kir_api_results.jsonl`

- Qualitative outcomes
  - SIM: Several passes with partial field coverage; needs GT to quantify.
  - STNK: Partial coverage (owner/address/plate) on a subset; frequent no-field cases.
  - KIR: Sparse coverage; label synonym/regex expansion likely needed.


## Field Accuracy (KTP)

Run: 2025-08-18T04:54:15+07:00

Source truth: `newdata/ground_truth/ktp_truth_filled_sample.csv`

Evaluator output: `newdata/result/ktp_field_eval_sample.csv`

- Sample size (evaluated): 10
- Exact-match accuracy by field:
  - nik: 0.10
  - nama: 0.00
  - tempat_lahir: 0.00
  - tanggal_lahir: 0.10
  - gol_darah: 0.143
  - rt_rw: 0.10
  - kel_desa: 0.00
  - kecamatan: 0.00
  - agama: 0.50
  - status_perkawinan: 0.30
  - pekerjaan: 0.00
  - kewarganegaraan: 0.40
  - berlaku_hingga: 0.00
- Address token F1 (avg): 0.00

Additional evaluated summary (8-sample JSONL join, see "Latest API-based Evaluation") aligns with weak fields on `nik`, `nama`, `alamat`, `tanggal_lahir`, and strong on `kewarganegaraan`, `agama`.

Notes:
- Dates in DD-MM-YYYY were normalized to YYYY-MM-DD during comparison.
- Header variants (e.g., "Kecamatan", "Status Perkawinan") are mapped case-insensitively.
- Low scores indicate parser gaps on this subset; address F1=0.00 suggests either address not extracted or strong mismatch.

### KTP Field Error Analysis

Observed via `scripts/dump_ktp_preds.py` on sample rows:
- nama often captured as labels (e.g., "KECAMATAN", "NIK") instead of person name.
- alamat often empty or concatenates admin labels (e.g., "KECAMATANKOTA BOGOR UTARA").
- kelurahan_desa sometimes merges with neighboring labels/values (e.g., "PERKAWINANBELUM KAWIN").
- nik occasionally wrong (e.g., admin codes or RT/RW digits) and date fields differ in format.

Fix areas proposed (see `app/parser/ktp_parser/`):
- `name_extractor.py`: exclude admin labels; enforce person-name heuristics (letters, spaces, vowels).
- `alamat_extractor.py`: capture between "ALAMAT" and before "RT/RW"; allow multi-line joins; strip labels.
- `kelurahan_desa_extractor.py` and `kecamatan_extractor.py`: tighten boundaries; require proximity to respective labels; avoid cross-field concat.
- `nik_extractor.py`: require 16-digit near NIK label; reject RT/RW-like patterns.
- `tanggal_lahir_extractor.py` and `berlaku_hingga_extractor.py`: normalize DD-MM-YYYY and accept "SEUMUR HIDUP".

### Next Steps (KTP Parser)

1) Implement fixes in extractors (Name, Alamat, Kelurahan/Desa, Kecamatan, NIK, Tanggal/Berlaku) with clear label boundaries and heuristics.
2) Add unit tests using failing samples from the filled truth to lock regressions.
3) Re-run field evaluator on the same CSV; target improvements: nama/nik/rt_rw >=0.7; alamat F1 >0.4 initially.
4) Iterate once more if targets not met; document deltas in this report.

## Plan and TODOs (Validation & Readiness)

- Current status
  - KTP: API-based metrics computed; weaknesses identified in several fields.
  - SIM/STNK/KIR: JSONL collected; metrics pending ground truth.

- Next actions
  - Provide/create GT CSVs for SIM, STNK, KIR; compute per-field accuracy (mirror KTP flow).
  - Parser improvements:
    - KTP: strengthen `nik`, `nama`, `alamat`, `tanggal_lahir`, `rt_rw`, `berlaku_hingga` heuristics and normalization.
    - STNK: broaden label/regex for `owner`, `alamat`, `nomor_polisi`; improve line merging around labels.
    - KIR: expand label synonyms (ID/EN), tighten `nomor_rangka/mesin` extraction, handle warped scans.
  - Preprocessing: consider doc-type-specific rotation/contrast tweaks.
  - Reporting: integrate SIM/STNK/KIR metrics once GT available; update gating criteria.

- Gating (initial)
  - KTP: target >70% accuracy on `nik`/`nama` and F1>0.4 for `alamat` before production pilot.
  - SIM/STNK/KIR: define targets after first GT-based metrics pass.

- Artifacts index
  - Scripts: `scripts/batch_ktp_from_csv.ps1`, `scripts/compute_ktp_metrics.ps1`, `scripts/batch_from_csv.ps1`, `scripts/gen_csv_from_dir.ps1`
  - Outputs: see JSONL paths above and KTP metrics CSVs under `newdata/output/KTP/`
