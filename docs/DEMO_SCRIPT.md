# Naskah demo (10–12 menit) — tunjukkan bagus dulu, baru minta

Persiapan (sebelum pertemuan):
1. `docker-compose up -d` (atau `REQUIRE_API_KEY=false python -m uvicorn app.main:app --port 8000`
   dengan env detektor bila memakai jalur ML).
2. Buka `http://localhost:8000/demo` di browser.
3. Siapkan foto di satu folder: 1 foto dokumen BAGUS (SIM/KTP), 1 SIM
   kedaluwarsa, 1 foto dompet (KTP+SIM), 1 scan KIR, 1 gambar acak
   (struk/berkas Word). HANYA gunakan specimen / foto yang sudah diizinkan.
4. Buka `evidence_before_after.html` (folder data, BUKAN repo) di tab kedua.

## Urutan babak — nilai dulu, permintaan terakhir

**1. "Foto bagus → semua field keluar" (90 detik) — INI PENENTUNYA**
Tarik foto dokumen bagus ke Ekstraksi (jenis AUTO) → tabel field terisi
penuh: NIK/nomor, nama, tanggal, semua. Kalimat: *"Pada foto yang layak,
sistem membaca SELURUH field — 28 dari 28 field berlabel pada sampel
uji, 100%."* Lalu buka tab bukti (`evidence_before_after.html`): foto
asli + OCR mentah + tiga tahap pipeline, semuanya hijau.

**2. "Satu foto dompet, dua dokumen" (60 detik)**
Foto KTP+SIM → MULTI, keduanya terurai. Kalimat: *"Vendor lain
mengembalikan kasus ini sebagai error."*

**3. "Sistem yang mengambil keputusan berangkat" (2 menit)**
Tab Verifikasi: SIM kedaluwarsa + klaim benar → NO_MATCH, alasan
`sim_expired`. Lalu nama pengemudi salah → checks mismatch.
Kalimat: *"Keluarannya GO / NO-GO dengan alasan mesin. Yang tak terbaca
menjadi review — tidak pernah menjadi GO yang salah."*

**4. "KIR hanya kami yang punya" (2 menit)**
Scan KIR → ekstraksi termasuk JBB / daya angkut / masa berlaku.
Kalimat: *"Tidak ada vendor yang melayani KIR. Field berat ini menjadi
gerbang kepatuhan ODOL saat booking — sebelum truk dimuat. Masa berlaku
menggerakkan pengingat uji 6 bulanan."*

**5. "Sistem tahu kapan harus menolak" (90 detik)**
Tarik gambar acak → UNKNOWN + alasan foto ulang. Sebutkan tiga penjaga
lain (sudah terukur): berkas Word berisi data KTP ketikan → ditandai
`missing_card_header`; fotokopi → `grayscale_possible_photocopy`
(kebijakan per alur); foto salah slot (SIM di kolom KTP) →
`document_type_mismatch` + jenis yang sebenarnya.
Kalimat: *"8 dari 8 input sampah ditangani benar — sistem verifikasi
harus tahu kapan berkata TIDAK."*

**6. "Kenapa tidak pakai ChatGPT saja?" (1 menit — biarkan mereka tanya)**
Jawaban dari RFC: batas kepatuhan (UU PDP — scan tidak pernah keluar dari
infrastruktur Anda), moda kegagalan (nilai halusinasi-tapi-masuk-akal vs
needs_review), auditabilitas, biaya pada skala armada. *"Mesin OCR bisa
diganti; lapisan verifikasinya yang menjadi produk."*

**7. Permintaan (terakhir, setelah nilai terbukti)**
Serahkan RFC (docs/RFC.md) + playbook. Permintaannya bisa dijalankan
tim Anda sendiri tanpa kami: (1) pilot mode bayangan — kontainer berjalan
di samping trafik nyata, keputusan dicatat bukan dipaksakan; (2) ukur
dengan data sendiri — harness evaluasi + panduan pelabelan sudah di
repo; (3) harness pembanding Google Cloud Vision tersedia satu perintah.

## Jika ditanya angka
Kutip TIER, jangan rata-rata semua field: **Tier-1 (field gerbang
dispatch) 86%** — plat STNK 100%, nomor SIM 90%, masa berlaku SIM 90%,
plat KIR 86%, NIK 85%; per jenis: SIM 92%, KIR 80%, KTP 79%, STNK 69%;
**sampel bagus 28/28 (100%)**. Setiap meleset masuk review, bukan
keputusan salah.

## Jika mesin demo bermasalah
`docs/img/` berisi tangkapan layar; logbook memuat semua angka beserta
tanggalnya; halaman bukti bisa dibuka tanpa server.
