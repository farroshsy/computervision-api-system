# Metode terbaik per jenis dokumen (bukan satu cara untuk semua)

Tiap jenis punya karakter beda, jadi pipeline memilih **metode yang paling
baik untuk jenis itu**, lalu menggabungkan hasilnya dengan aturan
"nilai-valid mengalahkan nilai-tak-valid". Angka di bawah dari benchmark
42 dokumen nyata (ground-truth manusia, spec field Logisly).

| Jenis | Skor | Metode utama (yang paling menaikkan) | Detektor YOLO? |
|---|---|---|---|
| **SIM** | **90%** | Aturan + **spatial pairing** (nomor/nama/golongan/masa-berlaku) | ⚪ dilatih (sintetis), OFF — tanpa gain terukur |
| **KTP** | **87%** | **Detektor** + spatial + **gazetteer** (kota/kecamatan/tempat) + **aritmetika NIK** (tgl-lahir/gender/perbaikan) | ✅ dipakai |
| **KIR** | **86%** | Aturan + spatial + **data-referensi** + **perakit dimensi** (P×L×T bergerbang plausibilitas) | ⚪ dilatih (sintetis), OFF — tanpa gain terukur |
| **STNK** | **83%** | **Detektor** (plat 33%→100%) + spatial + **pemulihan plat** + jenis | ✅ dipakai |

> **Detektor SIM/KIR (data sintetis) — hasil jujur.** Detektor field SIM & KIR
> kini DILATIH (synthetic cards, mAP50 0,995; terbukti generalisasi ke foto
> nyata — membaca nama nyata). Tapi pada benchmark 21 dokumen SIM/KIR nyata,
> **skor tidak berubah** (SIM 90→90, KIR 86→86, 0 nilai salah baru). Sebabnya:
> pipeline aturan+spatial SUDAH menangkap field yang bisa dilokalisasi, dan
> sisa yang meleset **terbatas-pengenalan** (OCR tak sanggup baca pikselnya) —
> detektor memperbaiki *di mana* field, bukan *pixel tak terbaca*. Karena itu
> detektor ini **OFF secara default** (env-gated, seperti STNK/KTP), aman
> (fill-empty + gerbang pola), dan siap berbayar saat kendala pengikat
> (kualitas recognition / volume data) diatasi. Lihat
> `docs/SYNTHETIC_DETECTOR_TRAINING.md`.

## Kenapa beda-beda

- **STNK & KTP → detektor YOLO memimpin.** Field kunci (plat, NIK) tersebar
  di posisi tak-teratur pada foto arsip; detektor menemukan region-nya
  per-foto (robust, tak perlu align). Ini yang mengubah plat STNK 33%→100%.
  Detektor = "ekstraksi zona" versi tangguh.
- **SIM → aturan + spatial sudah terbaik (90%).** Layout SIM ringkas &
  konsisten; nomor/nama/golongan mudah dipasangkan lewat geometri label.
  Tak butuh detektor — menambahkannya marginal.
- **KIR → data-referensi + perakit dimensi.** Field logistik (JBB, daya
  angkut, dimensi) berupa angka berlabel; gazetteer + gerbang plausibilitas
  lebih tepat daripada detektor umum.

## Langkah terbaik BERIKUTNYA — juga berbeda per jenis

| Jenis | Sisa masalah | Lever terbaik berikutnya |
|---|---|---|
| STNK | plat sufiks salah-baca (`SCG→ACH`) | model recognition lebih besar (GPU-Linux) |
| KTP | nama salah-baca 1 huruf (`FAJAR→FAJAB`) | model recognition lebih besar |
| SIM | golongan pada foto semibad (`BI→B`) | foto lebih baik (standar capture) |
| KIR | dimensi/jenis pada foto jelek | detektor KIR terlatih (butuh data berlabel) |

## Soal ekstraksi zona koordinat-tetap (level 3)

Bukan metode terbaik untuk keempatnya saat ini:
- STNK/KTP sudah punya **detektor** (versi tangguh dari ide zona).
- SIM/KIR sudah bagus dengan aturan+spatial.
- Zona koordinat-tetap baru berbayar pada **capture ter-align** (`/capture`),
  bukan foto arsip. Kalau jalur capture jadi dominan, KIR (tanpa detektor)
  adalah kandidat pertama untuk template zona — atau, lebih tangguh, melatih
  detektor KIR dari data yang dikumpulkan mengikuti standar foto.

Intinya: **satu API, empat jalur** — tiap jenis memakai kekuatannya sendiri.
