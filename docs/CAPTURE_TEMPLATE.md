# Template capture — standar foto agar OCR mendekati 100%

Dua jalur foto yang berdampingan:

| Jalur | Untuk | Halaman | Kualitas |
|---|---|---|---|
| **Evaluasi arsip** | foto LAMA / tak berstruktur (kasus terburuk) | `/demo` | apa adanya |
| **Capture terpandu** | foto BARU, diambil di aplikasi | `/capture` | terstruktur, terjaga |

## Kenapa capture terpandu menaikkan akurasi

Akurasi OCR ditentukan input, bukan hanya model. Bank/e-KYC memakai bingkai
kartu karena foto yang **rata, penuh-bingkai, terang, tanpa silau** membuat:

1. setiap blok teks jatuh di posisi yang sama (resolusi cukup per karakter),
2. tak ada rotasi/perspektif yang harus dipulihkan,
3. tak ada latar/jari/pantulan yang mencemari deteksi teks.

Pada foto arsip, kesalahan terkonsentrasi di foto resolusi-rendah / miring /
silau. Capture terpandu menghilangkan sumber itu di hulu — jauh lebih murah
daripada memperbaiki model. Sisa salah-baca 1-karakter pada evaluasi arsip
(`FAJAR→FAJAB`, `SCG→ACH`) justru jenis yang paling terbantu resolusi tinggi.

## Yang sudah ada di `/capture`

- Kamera perangkat (`getUserMedia`, kamera belakang diprioritaskan).
- **Bingkai kartu per-jenis** (rasio aspek):
  - KTP / SIM = kartu ID-1 (85,6 × 54 mm → rasio 1,586, lanskap)
  - STNK = kartu lebih besar (≈1,42)
  - KIR = lembar potret (≈0,71)
- **Crop ke bingkai** sebelum kirim → OCR menerima kartu rapat & rata.
- **Gerbang kualitas langsung**: peringatan "terlalu gelap" / "kurang tajam /
  silau" sebelum foto diambil.
- Menjalankan endpoint publik yang SAMA (`/api/v1/ocr/file`) — tak ada
  perubahan di hilir. Server juga tetap mengembalikan alasan foto-ulang
  (`resolution_too_low`, `blurry_image`, `image_too_dark`) sebagai jaring kedua.

## Standar yang direkomendasikan untuk integrasi aplikasi

Agar OCR konsisten tinggi pada capture baru, alur aplikasi sebaiknya menegakkan:

| Parameter | Standar |
|---|---|
| Resolusi kartu di dalam bingkai | sisi pendek ≥ 600 px (idealnya ≥ 1000) |
| Pengisian bingkai | kartu memenuhi ≥ 85% bingkai |
| Kemiringan | < 5° (dipandu bingkai) |
| Pencahayaan | merata, tanpa titik silau di area teks |
| Format | JPEG kualitas ≥ 0,9, tanpa kompresi WhatsApp |

## Lanjutan (belum dibangun) — ekstraksi berbasis-zona

Karena capture terpandu menaruh setiap field di posisi tetap, langkah berikutnya
adalah **template zona**: untuk tiap jenis, definisikan kotak (x, y, w, h relatif
kartu) tempat NIK, nama, dst. berada; crop tiap zona, OCR terpisah. Pada foto
capture yang rata, ini mendekati 100% karena setiap crop hanya berisi satu
field pada resolusi penuh. Detektor field YOLO terlatih (STNK/KTP) sudah
melakukan versi robust-nya untuk foto tak-rata; template zona adalah versi
murah untuk capture yang sudah terstruktur.

Kunci: template zona hanya sah pada capture terpandu (posisi terjamin). Foto
arsip tetap butuh jalur deteksi/geometri yang ada — dua jalur, satu API.
