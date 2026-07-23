# RFC — Layanan Verifikasi Dokumen Pengemudi & Kendaraan

**Status**: proposal · **Tanggal**: 2026-07-12

## Masalah

Keputusan dispatch dan onboarding bergantung pada dokumen (KTP, SIM,
STNK, KIR) yang hari ini diperiksa manual, terlambat, atau tidak sama
sekali. Arsip foto yang ada terkumpul tanpa validasi: SIM kedaluwarsa,
surat kendaraan yang salah, dan foto yang dipakai ulang baru terlihat
setelah menjadi insiden, kiriman gagal, atau temuan kepatuhan.

## Usulan

**Microservice verifikasi stateless** (Docker, REST, autentikasi API key)
yang menjawab tiga pertanyaan operasional:

1. **Onboarding** — benarkah orang ini sesuai klaimnya?
   `POST /api/v1/verify/document` (KTP/SIM + klaim NIK/nama/tgl lahir)
   → `match / no_match / needs_review` + kode alasan mesin.
2. **Dispatch** — bolehkah pengemudi ini membawa truk ini, sekarang?
   `POST /api/v1/verify/trip` (foto SIM + STNK + KIR + klaim)
   → `GO / NO_GO / REVIEW`. Memeriksa kecocokan identitas, golongan SIM
   vs yang disyaratkan, masa berlaku SIM/KIR vs hari ini, plat vs truk
   yang ditugaskan.
3. **Higiene arsip** — apakah unggahan ini foto duplikat/daur ulang?
   `POST /api/v1/image/fingerprint` + `/image/match` — platform
   menyimpan fingerprint ringkas di basis datanya sendiri; layanan ini
   tidak menyimpan apa pun.

**Biaya integrasi**: REST + multipart; spesifikasi OpenAPI di
`/openapi.json` (client Go/Node/PHP satu perintah); koleksi Postman
(`docs/postman_collection.json`, lengkap dengan contoh respons error
400/401/413/422/429); resep copy-paste di `docs/API_COOKBOOK.md`;
konsol demo langsung di `/demo`.

## Prinsip desain

- **Stateless / tanpa retensi PII** — foto diproses lalu dibuang; tidak
  ada basis data di sisi kami; sistem platform tidak pernah disentuh.
- **Tidak pernah menolak salah karena foto jelek** — bukti yang tak
  terbaca masuk `needs_review` (antrean manusia / minta foto ulang);
  hanya bukti yang BERTENTANGAN yang menghasilkan `no_match`. Keputusan
  salah itu mahal; review itu murah.
- **Terukur, bukan janji** — semua angka akurasi di bawah berasal dari
  harness yang dapat direproduksi atas foto arsip nyata (kualitas
  terburuk).

## Akurasi terukur (n=41 foto arsip nyata, 197 field berlabel; detektor terlatih + pemetaan label→nilai berbasis geometri)

**Deteksi jenis dokumen: 39/41 (95%)** — dua yang meleset adalah foto
sangat buram yang jawaban benarnya memang "minta foto ulang".

**Pada foto tangkapan layak (sampel bagus): 28/28 field (100%)** —
bukti visual per field di `evidence_before_after.html` (disimpan
bersama data, bukan di repositori, karena memuat dokumen asli).

Logistik bergantung pada sekelompok kecil field; kami melaporkan field
itu, bukan rata-rata semua field yang tidak bermakna.

**Tier 1 — field gerbang (dispatch tidak bisa terjadi tanpanya):**

| Field | Peran | Akurasi |
|---|---|---|
| Plat STNK | identitas truk | **100%** (detektor terlatih) |
| Nomor SIM | identitas pengemudi | **90%** |
| Masa berlaku SIM | sah mengemudi | **90%** |
| Plat KIR | surat ↔ truk | **86%** |
| NIK KTP | identitas onboarding | **85%** |
| Masa berlaku KIR | laik jalan hari ini | 71% |

**Agregat Tier-1: 86%** — dan setiap yang meleset menjadi
`needs_review`, tidak pernah GO yang salah. Tier 2 (nama, golongan SIM,
silang nomor rangka, JBB/daya angkut untuk ODOL) berjalan ~83%. Per
jenis dokumen: SIM 92%, KIR 80%, KTP 79%, STNK 69%. Field di luar tier
diekstrak oportunistik dan tidak pernah dikutip.

Pada verifikasi langsung dokumen nyata: SIM kedaluwarsa terblokir
(`sim_expired`), klaim benar cocok, klaim pengemudi salah ditolak, foto
dompet mengembalikan kedua dokumen, 8/8 input sampah (struk, halaman
kosong, berkas Word berisi data KTP ketikan) ditolak atau ditandai —
nol keputusan salah.

## Rencana mitigasi akurasi (urut daya ungkit)

1. **Gerbang kualitas saat pengambilan foto** — kesalahan terkonsentrasi
   pada foto resolusi rendah; API mengembalikan alasan foto ulang
   (termasuk `resolution_too_low`) dan alur pengambilan foto harus
   menegakkannya. Akurasi termurah yang tersedia.
2. **Cakupan detektor field** — resep detektor terlatih membawa plat
   STNK dari 33% ke 100%; dataset field SIM/KIR adalah penghambat yang
   tersisa (pelabelan mandiri direncanakan). Pemetaan label→nilai
   berbasis geometri (tanpa model) + data referensi (gazetteer merek /
   kecamatan, tanggal lahir dari struktur NIK) sudah terpasang:
   KIR 54%→80%, STNK 38%→69%, KTP 65%→79%, SIM 78%→92% pada set uji
   yang sama.
3. Perbesar set evaluasi berlabel (lebih banyak scan KIR, uji lewat
   kompresi WhatsApp).

## "Kenapa tidak pakai ChatGPT saja?"

Model vision terbaru memang membaca dokumen dengan baik — dan sistem ini
tetap dibutuhkan tanpa berubah, karena empat hal. (1) Kepatuhan:
scan KTP/SIM memuat NIK, wajah, dan alamat warga; mengirimnya ke API
cloud asing adalah persoalan UU PDP dan DPA perusahaan. Ekstraksi di
sini berjalan di dalam infrastruktur Anda. (2) Moda kegagalan: field
kami yang tak terbaca menjadi needs_review; milik model bahasa bisa
menjadi nilai halusinasi yang masuk akal dan lolos pemeriksaan
sekilas — satu-satunya kegagalan yang tidak boleh terjadi pada gerbang
GO/NO_GO. (3) Auditabilitas: pipeline deterministik, akurasi per field
terukur, kode alasan mesin — keputusan dispatch tetap bisa dijelaskan
berbulan-bulan kemudian. (4) Biaya marginal pada skala armada: OCR
cloud (mis. Google Cloud Vision Document Text Detection, $1,50/1.000
gambar, per HALAMAN untuk PDF) ~$12/bulan pada skala pilot tetapi
~$675/bulan pada 5.000 trip/hari dan ~$6.700/bulan pada 50.000 — plus
backfill arsip dan scan ulang KIR tiap 6 bulan. Self-hosted berjalan di
perangkat keras yang sudah Anda miliki. Mesin OCR dengan demikian
adalah PILIHAN KONFIGURASI per deployment, diuji dengan data Anda,
bukan komitmen. Inti yang lebih dalam: mesin OCR itu komoditas dan bisa
diganti (lihat ADR-0001) — produknya adalah lapisan verifikasi: klaim,
pemeriksaan aritmetika, kontradiksi antar dokumen, gerbang masa berlaku
dan golongan, deteksi duplikat, dan keputusan tiga arah. Lapisan itu
membuat pembaca APA PUN — termasuk, kelak, model vision yang di-hosting
lokal — aman untuk dipakai.

## Keamanan

Autentikasi API key, rate limiting, batas unggahan; tanpa persistensi
gambar/PII; rahasia lewat environment; redaksi PII pada log. Verifikasi
Dukcapil di luar lingkup layanan ini tetapi bisa masuk rapi di belakang
antarmuka `verify` yang sama bila tim kepatuhan memperoleh akses.

## Perluasan ke depan (di luar lingkup sekarang)

ANPR (foto plat truk vs STNK/penugasan), validasi nomor kontainer
ISO 6346 (digit cek deterministik — endpoint dasar sudah ada di
`/api/v1/logistics/container`), digitalisasi POD, pencocokan wajah.

## Permintaan — bisa dijalankan tim Anda sendiri, tanpa kami

1. **Pilot mode bayangan**: kontainer stateless berjalan di samping
   trafik onboarding/dispatch nyata; keputusan dicatat, tidak
   dipaksakan. Nol risiko, nol PII keluar dari infrastruktur Anda.
2. **Ukur dengan data Anda sendiri**: harness evaluasi + format
   pelabelan sudah di repo (`scripts/eval_real_docs.py`); satu engineer
   dapat melabeli 30–50 foto arsip dalam satu sore dan mendapatkan
   tabel akurasi ber-tier versi Anda — tanpa perlu memercayai angka
   kami.
3. **Pembanding mesin OCR**: harness perbandingan Google Cloud Vision
   tersedia satu perintah (`scripts/eval_gcv.py`, butuh API key Anda) —
   Anda yang memilih mesin sesuai tata kelola data; lapisan verifikasi
   identik untuk keduanya.
