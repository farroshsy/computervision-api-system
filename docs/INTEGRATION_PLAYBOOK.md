# Integration Playbook — real workflows for a 3PL platform

How the API actually gets used, flow by flow. Every flow lists: trigger,
calls, decision handling, and what the human sees. Written for the
platform's backend team (any stack — REST + multipart only).

## Flow 1 — Driver onboarding (KYC)

**Trigger**: new driver registers; sends KTP + SIM photos (often ONE
wallet photo with both cards — that's fine, see below) via app or
WhatsApp bot.

1. `POST /api/v1/ocr/file` with `document_type=AUTO`.
   - Wallet photo → `document_type: "MULTI"` + `documents[]` with the
     KTP and SIM parsed separately. One upload, both documents.
2. Platform inspects `data.validation.reasons`:
   - `blurry_image` / `too_dark` / `very_low_text_content` → bot replies
     "foto ulang" with the specific tip. Cheap loop, no human.
   - `nik_dob_mismatch` / `nik_gender_mismatch` → route to review queue
     (real documents DO have these inconsistencies — a reviewer decides).
3. Cross-document check (free, offline): KTP name vs SIM name via
   `POST /api/v1/verify/document` per doc with the other doc's values
   as claims. Same person on both cards or review.
4. `POST /api/v1/image/fingerprint` on each accepted photo → store the
   fingerprint string in the driver's record (platform DB, not ours).
5. Persist extracted profile fields as PREFILL, show to the driver for
   confirmation — extraction is assistive, the driver confirms.

**What ops sees on review**: per-field extracted vs expected, reason
codes, and the photo. Decision in seconds, not re-typing.

## Flow 2 — Dispatch gate (GO / NO_GO / REVIEW)

**Trigger**: TMS assigned driver X + truck Y to an order; driver at the
yard scans SIM + STNK + KIR.

1. `POST /api/v1/verify/trip` with the three photos + claims from the
   TMS record: `driver_name`, `sim_number`, `plate`, `required_classes`
   (e.g. `"BII,BII UMUM"` for heavy trucks).
2. Decision handling:
   - `GO` → release the trip. Log the per-document evidence.
   - `NO_GO` → block with the reason shown to the dispatcher:
     `sim_expired`, `kir_expired`, `sim_class_not_allowed`, plate
     mismatch. These are legal no-gos, not suggestions.
   - `REVIEW` → dispatcher sees which field was unreadable, decides:
     retake photo (10 seconds) or manual check.
3. Latency reality (CPU): card photos ~3–8s, full-page KIR ~30s. Call
   the trip check when the driver starts walking to the truck, not when
   the engine is running. For high volume: GPU container or a queue +
   webhook callback.

## Flow 2b — STNK: the truck's identity paper

STNK is the link between a physical truck and everything else: the
plate (nomor polisi) on the STNK must equal the plate on the KIR, the
plate in the TMS assignment, and the plate on the actual truck. Uses:

- **Truck onboarding**: scan STNK once → plate, rangka (VIN), mesin,
  brand/type, year → the TMS truck record is created from the document,
  not typed by hand (typos in rangka numbers are unfixable later).
- **Dispatch**: `/verify/trip` checks claimed plate vs STNK photo.
- **Cross-document integrity**: STNK rangka == KIR rangka — if they
  differ, someone is showing papers from two different trucks.
- **Tax currency**: the SKPD/pajak page carries the tax expiry
  (`tax_valid_to`) — an expired-tax truck risks being stopped.
- Future: ANPR (photo of the truck's actual plate at the gate) closes
  the loop document -> physical vehicle.

## Flow 3 — Load planning / ODOL compliance (unique to this API)

Kemenhub's ODOL (Over-Dimension Over-Load) enforcement makes overweight
trips a legal and commercial risk. The KIR card states the legal limits
— and this API extracts them (`jbb_kg`, `daya_angkut_kg`,
`berat_kosong_kg`, `kelas_jalan`):

- At truck onboarding, scan KIR once → store legal capacity per truck.
- At order booking: `order_weight <= daya_angkut_kg` or the TMS refuses
  the assignment — BEFORE the truck is loaded, not at a weighbridge.
- `kelas_jalan` gates route planning (class III truck ≠ class I roads).

No competitor extracts these fields; they are the difference between
"document OCR" and "operations data".

## Flow 4 — Archive hygiene & fraud signals

The existing photo archive was collected unvalidated. One-time backfill:

1. For each archived image: `POST /api/v1/image/fingerprint` → store
   fingerprint next to the record (batch script, archive never leaves
   the platform).
2. Every new upload: `POST /api/v1/image/match` with the driver's own
   previous fingerprints (same doc re-uploaded = fine) AND a sample of
   the global set → **same image under a different driver = fraud flag**.
3. Re-run extraction over the archive to find: expired KIR/SIM still
   marked active, plate mismatches between STNK and TMS records.

## Flow 5 — Expiry watchdog

Every successful KIR/SIM scan yields `valid_until` / `expiry_date`.
Store per truck/driver; a daily job flags documents expiring in 30/7/0
days → WhatsApp reminder to the transporter. KIR renews every 6 months —
this single feature pays for the integration in avoided idle trucks.

## Capture guidance (send to the driver-facing team)

- Minimum ~1000px on the document's short side; the API's reason codes
  drive the retake UX — surface them, don't invent your own heuristics.
- One document per photo is ideal; two stacked cards are handled (MULTI)
  but four are not.
- KIR: photograph the FULL page, flat; the QR code (top-right) when
  sharp gives `data.qr_codes` — the authoritative Kemenhub link.
- Mirrored photos (front camera) are auto-corrected; rotation is
  auto-corrected; photocopies work but color originals read better.

## Photocopy & replica policy (decide per flow, the API only reports)

A photocopy or scan can carry perfectly readable, perfectly correct
data — what it cannot prove is that the person HOLDS the original.
The API therefore never hard-rejects one; it raises advisory reasons
and each flow applies its own policy:

- `grayscale_possible_photocopy` — the image has no color (measured:
  real copies/scans sit at saturation 0-2, every real photo >=4).
- `missing_card_header` — field keywords present but the card's printed
  header (PROVINSI / SURAT IZIN MENGEMUDI / KEPOLISIAN / UJI BERKALA)
  is absent: consistent with data TYPED into a document, not a card.

Suggested policy:

| Flow | photocopy/scan | typed replica suspicion |
|---|---|---|
| Onboarding (identity) | reject -> request live capture of original | reject -> request live capture |
| Dispatch gate-check | accept or review (data verifies against claims) | review |
| Archive backfill | accept, tag for later re-capture | tag |

Boundary stated honestly: a COLOR print of a photo, or a replica that
also types the card header, passes text-level checks. Catching those
needs capture-time liveness or physical inspection — roadmap, and true
of every OCR-based system.

## Deployment shape

- `docker-compose up -d` — stateless container, scale horizontally.
- No PII stored: images processed in-memory/temp and discarded; logs
  redacted. Platform keeps all records on its side.
- API key per consumer; rate limits configured via env.
- Health: `/api/v1/health`; metrics: Prometheus `/metrics`.
