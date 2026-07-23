# 0001 — Verification-first architecture; extraction engines are replaceable

**Status**: accepted · **Date**: 2026-07-12

## Context

Frontier vision LLMs (GPT-4o, Claude) read Indonesian documents well —
often better raw transcription than a self-hosted OCR stack on messy
photos. Any buyer will ask: "why not just use ChatGPT?" The product
must have a true answer, not a defensive one.

## Decision

The product is the **verification system**, not the OCR engine:
claims comparison, NIK/check-digit arithmetic, cross-document
contradiction, expiry/class gates, fingerprint dedup, three-way
decisions with machine reasons. Extraction is a **replaceable
backend** behind that layer (today: PaddleOCR v6 + trained field
detectors; tomorrow: possibly a locally-hosted VLM for review cases).

## Rationale (the trade-off)

- **Compliance boundary**: KTP/SIM scans carry NIK, face, address of
  real citizens. Sending them to a foreign cloud API is a UU PDP and
  enterprise-DPA problem; self-hosted extraction is a requirement,
  not a preference. This is why domestic KYC vendors exist in a world
  that already has ChatGPT.
- **Failure-mode asymmetry**: our unreadable field becomes
  needs_review; a VLM's unreadable field can become a HALLUCINATED
  plausible value that passes casual review. For a legal GO/NO_GO
  gate, confident invention is the disqualifying failure mode.
- **Auditability**: deterministic pipeline + per-field eval harness +
  versioned behavior + machine reason codes. A dispatch decision must
  be explainable months later.
- **Marginal cost**: 6-monthly KIR renewals across a ~100k-truck
  network plus daily dispatch scans; per-image API pricing forever vs
  an owned container.

## Consequences

- We never claim to out-read frontier VLMs; we claim the verification
  layer makes ANY reader deployable. Pitch materials must carry this
  framing explicitly.
- A locally-hosted VLM (e.g. Qwen-VL class) as an optional extraction
  backend for needs_review cases is a legitimate roadmap item — it
  slots UNDER the verification layer, PII stays on-prem.
- Review queues are a feature (routing quality, reasons), not an
  admission of weakness; the KPI is review RATE, not its existence.
