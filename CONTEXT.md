# Context — Indonesian Document Verification

Glossary of terms as used in this product. Code, docs, and pitch
material must use these words with exactly these meanings.

## Capabilities (do not conflate)

**Detection** — identifying WHICH document type an image contains
(KTP, SIM, STNK, KIR), or UNKNOWN when the evidence is insufficient,
or MULTI when one photo contains several documents. Measured
separately from extraction.

**Extraction** — reading the field values off a detected document
(NIK, plate number, expiry...). Accuracy is per-field and per-type;
quoting one aggregate number for "accuracy" is meaningless without
saying which fields.

**Verification** — comparing extracted values against CLAIMS supplied
by the caller, plus document-intrinsic checks (expiry vs today, SIM
class vs required class). Produces a Decision.

## Terms

**Claim** — a value the caller asserts about the expected document
("this should be SIM number X, driver named Y"). Verification never
invents claims; no claims means nothing to verify.

**Decision** — the three-way verification outcome:
- `match` — every provided claim matched; no blocking fact
- `no_match` — a readable value CONTRADICTS a claim, or the document
  itself is invalid for use (expired, wrong class)
- `needs_review` — insufficient readable evidence to decide; routed
  to a human or a retake, never silently rejected

**Trip decision** — the aggregate over a document set for one
dispatch: GO / NO_GO / REVIEW.

**Retake signal** — machine reason codes (blurry_image, too_dark,
very_low_text_content) that tell the capture UX to ask the user for a
new photo instead of guessing.

**MULTI / wallet photo** — one photo containing multiple documents
(typically KTP + SIM). Split and parsed per document; never treated
as an error.

**Document-intrinsic check** — a validity fact requiring no claim:
expiry date vs today, SIM class against required classes, NIK
self-consistency (region/birthdate/gender encoding).

**Fingerprint** — a compact perceptual hash of an image, stored by
the CALLER in their own systems, used to detect duplicate or reused
document photos. This service stores nothing.

**Forgery signal** — evidence that a document or its photo is not what
it claims to be. This product provides CONSISTENCY-based signals
(arithmetic and cross-checks); it does NOT authenticate physical
security features. The layers, weakest-to-strongest:
1. self-consistency (NIK encoding vs printed data, container check digit)
2. cross-document contradiction (KTP vs SIM disagree)
3. claim contradiction (document vs what the platform expects)
4. image reuse (same fingerprint under different identities)
5. authoritative source (KIR QR to the government record; Dukcapil-class
   registries are the caller's integration, not ours)
