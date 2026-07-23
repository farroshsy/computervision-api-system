# Menjalankan demo di Mac (Intel) — runbook transfer

Semua yang dibutuhkan presentasi, tanpa internet, tanpa bergantung PC.

## Yang dibawa dari PC (USB / AirDrop)

| # | Item | Sumber di PC | Catatan |
|---|---|---|---|
| 1 | `ocr-api-demo.tar` (image Docker) | `docker save ocr-api:demo -o ocr-api-demo.tar` | ~4-6 GB; berisi kode + dependensi + profil ML |
| 2 | Folder `evidence/` | `D:\Code\id-document-verification-api\evidence\` | bukti + laporan + 4 foto Uji Cepat (PII — jangan lewat git) |
| 3 | Folder `models/` | `D:\Code\id-document-verification-api\models\` | 2 bobot YOLO (~46 MB) |
| 4 | `docker-compose.demo.yml` | repo | atau clone repo bila sudah di-push |
| 5 | Foto demo | folder LOGISLY (pilih sesuai naskah) | SIM kedaluwarsa, foto dompet, KIR, gambar acak |

## Di Mac (sekali saja, sebelum presentasi)

```bash
# 1. muat image
docker load -i ocr-api-demo.tar

# 2. susun folder kerja
mkdir demo && cd demo
#    letakkan: docker-compose.demo.yml, evidence/, models/

# 3. jalankan
docker compose -f docker-compose.demo.yml up -d

# 4. cek
open http://localhost:8000/demo
```

Checklist verifikasi (2 menit, lakukan MALAM SEBELUMNYA):
- [ ] Konsol tampil dalam Bahasa Indonesia
- [ ] Tombol Uji Cepat muncul (4 sampel) dan satu klik menghasilkan field
- [ ] Tarik-lepas foto ke zona Ekstraksi → hasil keluar
- [ ] `Bukti` dan `Laporan` terbuka dari tautan atas
- [ ] Verifikasi SIM kedaluwarsa → NO_MATCH `sim_expired`

## Alternatif: build dari repo (tanpa tar)

Bisa — dengan dua syarat. Butuh internet + waktu di Mac (unduhan
dependensi ~2-3 GB + model OCR ~200 MB pada RUN PERTAMA), jadi WAJIB
dikerjakan MALAM SEBELUMNYA, bukan di lokasi:

```bash
git clone https://github.com/farroshsy/computervision-api-system && cd computervision-api-system
# salin evidence/ dan models/ dari PC (tetap harus dibawa — tidak di git)
docker compose -f docker-compose.demo.yml up -d --build
# lalu buka /demo dan JALANKAN SATU EKSTRAKSI agar model OCR terunduh
```

Tar tetap opsi paling bebas-kejutan: tanpa build, tanpa internet
(model OCR sudah tertanam di dalamnya).

## Jika Docker bermasalah di Mac (cadangan)

Jalankan natif (butuh internet sekali untuk pip):

```bash
git clone https://github.com/farroshsy/computervision-api-system && cd computervision-api-system
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt -r requirements-ml.txt
cp -r /path/ke/evidence ./evidence
REQUIRE_API_KEY=false \
FIELD_DETECTOR_STNK_WEIGHTS=./models/stnk_fields.best.pt \
FIELD_DETECTOR_KTP_WEIGHTS=./models/ktp_fields.best.pt \
uvicorn app.main:app --port 8000
```

## Catatan arsitektur

Image dibangun `linux/amd64` — cocok untuk Mac INTEL. JANGAN dipakai di
Mac Apple Silicon (PaddlePaddle butuh AVX; emulasi Rosetta tidak
mendukungnya — akan crash). Untuk M-series, build ulang `--platform
linux/arm64` atau pakai jalur natif di atas.
