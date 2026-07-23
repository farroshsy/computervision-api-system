# Handoff — moving this work to the GPU box (and back)

State as of 2026-07-13. Written for the next person to pick this up, who may be
you in a week.

## What this is

The demo was declared "done" once. It was not. Measuring it against the
customer's own 42 documents — with human ground-truth labels, which had never
existed — found that the pipeline was **confidently wrong on 28 required
fields**, and that the same photo could return different answers on two
consecutive runs.

Both are fixed. The numbers below are real and reproducible.

## Where things are

| What | Where | Travels to the PC? |
|---|---|---|
| The code, with all the fixes | this repo, branch `fix/kyc-accuracy-and-ocr-determinism` | **yes** — `git push`, or copy the folder |
| The demo kit (compose files, runbook, deck) | `ocr-api-demo-kit/` on the Mac | yes — plain files |
| The 42 customer documents | `ocr-api-demo-kit/evidence/samples/Customer KYC/` | **PII — see below** |
| Ground-truth labels (NIK, names, addresses) | session scratchpad only | **PII — see below** |
| Trained YOLO detector weights | `ocr-api-demo-kit/models/*.pt` | yes — needed, not sensitive |
| Docker image `ocr-api:demo` (3.03 GB) | local Docker | optional — rebuildable from source |

### The PII rule, unchanged

The documents and the labels are **real identity documents**. They do not go to
GitHub, they do not go to any cloud service, they do not go in this repo.
`.gitignore` already blocks `evidence/` and `models/`. Move them between your
machines **by hand** — USB, or a direct local copy. Nothing else.

## Getting it running on the PC

### Fastest path (CPU, same as the Mac)

```bash
git clone <this repo> && cd ocr-api
git checkout fix/kyc-accuracy-and-ocr-determinism
# copy evidence/ and models/ over BY HAND from the Mac, then:
docker compose -f docker-compose.demo.yml up -d --build
open http://localhost:8000/demo
```

### Using the GPU — the actual point of the move

The OCR is the slow part: **5–190 seconds per page** on the Mac's CPU. A full
42-document benchmark run takes ~25 minutes. That is what the GPU buys you.

**Read this first, because the flag lied before today:** the code has always had
a `PPOCR_USE_GPU` env var, but the PaddleOCR-v3 branch hardcoded CPU and returned
early — so setting it printed `use_gpu=True` in the log and still ran on the CPU.
That is fixed (`paddle_ocr.py`); the flag now actually selects the device, and if
you ask for GPU without a CUDA build of Paddle installed it **falls back to CPU
with a warning** instead of pretending.

```bash
pip install -r requirements.txt -r requirements-ml.txt
# then replace the CPU wheels with CUDA ones — see requirements-gpu.txt
PPOCR_USE_GPU=1 uvicorn app.main:app --port 8000
```

Confirm it took:

```
PaddleOCR v3 pipeline initialized (lang=en, device=gpu)   <- what you want
PaddleOCR v3 pipeline initialized (lang=en, device=cpu)   <- GPU wheel missing
```

Two frameworks need CUDA independently: **PaddlePaddle** (the OCR — the slow
part) and **PyTorch** (the YOLO field detectors — small). Getting only torch on
the GPU will not make pages faster.

**Docker + GPU:** the shipped compose files are CPU-only. You need
`--gpus all` / `deploy.resources.reservations.devices` and an NVIDIA base image.
Running natively (venv, no Docker) is the shorter road on a dev box.

### Caution: one fix is CPU-shaped

Every Paddle predict is pinned to **one long-lived thread** (`_OCR_EXECUTOR` in
`paddle_ocr.py`), because the CPU predictor is thread-*affine*: called from a
fresh thread each time, it intermittently threw `std::exception`, the page read
as zero lines, and the request silently degraded. That was the nondeterminism.

On GPU the constraint may not apply, and serializing inference would waste the
card. **Do not just delete it** — re-test determinism first: same image, five
runs, identical output. The test that caught it is in the section below.

## Reproducing the numbers

`accuracy.py` and `run_ocr.py` (the benchmark harness) are plain scripts with no
PII. The **labels they score against are PII** and are not in this repo.

```bash
# 1. run all 42 documents through the API, serialized (OCR is not thread-safe)
OCR_PORT=8000 OCR_OUT=results python run_ocr.py "/path/to/Customer KYC"

# 2. score against human ground truth
python accuracy.py
```

The scorer grades the field list from **the customer's own deck**, not ours —
including two fields (KTP "ID registration place", STNK "Type of registration")
that were never extracted or even scored before, and excluding STNK `warna`,
which they never asked for.

Determinism check (this is what caught the worst bug):

```bash
# same image, five times, through the running API — outputs must be identical
for i in 1 2 3 4 5; do
  curl -s -X POST localhost:8000/api/v1/ocr/file -F file=@ID_standard.jpeg \
       -F document_type=AUTO | jq -c '.data.fields | {nik:.nik.value, nama:.nama.value}'
done
```

## Results (42 documents, customer's field list, human ground truth)

| doctype | correct before | correct now | **wrong before → now** |
|---|---|---|---|
| KTP | 38% | 82% | 8 → 2 |
| SIM | 80% | 90% | 0 → 0 |
| STNK | 42% | 71% | 15 → 4 |
| KIR | 19% | 78% | 5 → **0** |
| **total** | — | — | **28 → 6** |

"Wrong" is the bucket that matters: a wrong value is filed into a KYC record and
never reviewed, while a missing one becomes `needs_review` and a human catches
it. Trading wrong values for missing ones is a win, and most of the remaining
gap is exactly that trade.

The last 6 wrong values are single-character OCR misreads (`FAJAR`→`FAJAB`,
`PASURUAN`→`PAJURUAN`, `SCG`→`ACH`). No guard can reject those without also
rejecting real names and real plates. They need better recognition, not more
rules — which is the next thing a GPU box makes practical to try.

## What actually got fixed (so you don't re-litigate it)

1. **Nondeterminism** — one long-lived OCR thread (above). SIM accuracy rose
   80%→90% from this alone, with zero parser changes.
2. **Correct text, wrong field** — `model` was read from the TYPE row instead of
   MODEL; a plate-shaped regex then carved a fake plate out of that type code.
3. **Two documents in one photo** — a third of the STNK photos show the card AND
   the tax receipt, and *both* print `BERLAKU SAMPAI`. The pipeline reported the
   receipt's date as the card's expiry.
4. **Validation** — plate region codes are a closed set; a NIK has structure (and
   encodes both birth date and sex); sex is a two-value vocabulary; dates have a
   plausible range. A value failing these is **dropped to needs_review, not
   guessed**. `meta.trace.dropped` reports every one, with its reason.
5. **`bbox` per field** — the customer's spec draws a numbered box around each
   wanted field. The detector was already computing those boxes and discarding
   them. They are now returned and drawn in the console.
6. **KIR pass/fail is inferred, and says so** — the card never prints a result;
   an unexpired KIR *is* the proof of passing. That value carries
   `provenance.inferred = true` and a confidence below anything OCR produces. On
   a truck safety certificate, "the card says so" and "we concluded it" must
   never look the same.

## Known-good state to come back to

- Rollback image tag on the Mac: **`ocr-api:demo-orig`** (the pre-fix demo).
  `docker tag ocr-api:demo-orig ocr-api:demo && docker compose -f docker-compose.demo.yml up -d --force-recreate app`
- The console (`/demo`) has a gallery of all 42 documents; click one and it shows
  what OCR saw, where each field was found, what was dropped and why, and the
  result. That is the demo.
