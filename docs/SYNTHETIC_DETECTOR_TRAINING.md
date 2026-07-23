# Melatih detektor field SIM & KIR dari data sintetis

## Masalahnya (kenapa tidak sekadar "ambil dari Google")

Detektor field YOLO butuh gambar **beserta kotak posisi tiap field**
("nama ada di kotak [x,y,w,h]"). Yang kita punya untuk SIM/KIR:

- **~10-11 foto nyata** per jenis — jauh dari cukup (detektor STNK dilatih
  pada 213 gambar).
- Ground-truth **hanya berupa teks** (nilai field), **bukan kotak posisi**.

Mengambil dari Google Image **tidak menyelesaikan hambatan sebenarnya**:
Google memberi piksel, bukan kotak — tiap gambar tetap harus dianotasi kotak
dengan tangan. Lebih buruk lagi, foto SIM asli di internet adalah **identitas
orang nyata** (nama, NIK, alamat, wajah): melatih verifikator KYC produksi di
atas identitas hasil scraping adalah masalah privasi & hak cipta, bukan jalan
pintas.

## Solusinya: render kartu sintetis dari layout publik

SIM (format baru Polri, 1 Juli 2024) dan KIR (kartu uji nasional) punya
**layout tetap** — posisi tiap field konsisten di semua kartu jenis yang sama.
Maka kita **menggambar** kartu sintetis dengan nilai palsu-tapi-valid (NIK
palsu, nama dari kumpulan, plat dari 58 kode wilayah nyata, VIN, dimensi) pada
posisi yang **kita tentukan sendiri**. Karena kita yang menaruh field-nya,
**kotaknya eksak dan gratis** — termasuk untuk field yang OCR pun tak sanggup
baca. Augmentasi berat (warp perspektif, pencahayaan, blur, noise, latar)
membuatnya menyerupai foto ponsel.

```
scripts/synth_cards.py   → gambar + label OBB (Roboflow) + data.yaml
scripts/train_field_detector.py → yolov8s-obb, sama seperti STNK/KTP
```

## Garis kejujuran (penting untuk sidang / Logisly)

> Data sintetis dipakai **hanya untuk MEMPELAJARI di mana field berada.**
> Akurasi **selalu diukur pada 10-11 sampel NYATA**, ditahan (held-out),
> tak pernah ikut dilatih.

Angka akurasi yang dilaporkan tetap bersumber dari dokumen nyata. Ini bukan
"memalsukan hasil" — ini teknik standar *synthetic data* untuk document AI,
persis seperti detektor MRZ/field paspor yang di-bootstrap dari template.

## Reproduksi

```bash
# 1. bangun data (label eksak, dibuat bersama pikselnya)
python scripts/synth_cards.py --type SIM --n 1500 --out ./train_runs/data/sim_synth
python scripts/synth_cards.py --type KIR --n 1500 --out ./train_runs/data/kir_synth

# lihat kotak menempel benar (opsional):
python scripts/synth_cards.py --type SIM --preview 5 --out ./train_runs/data/sim_synth

# 2. latih (RTX 2060, ~1 jam/jenis @ 80 epoch)
python scripts/train_field_detector.py --data ./train_runs/data/sim_synth/data.yaml --name sim_fields
python scripts/train_field_detector.py --data ./train_runs/data/kir_synth/data.yaml --name kir_fields

# 3. aktifkan di pipeline
setx FIELD_DETECTOR_SIM_WEIGHTS ./train_runs/sim_fields/weights/best.pt
setx FIELD_DETECTOR_KIR_WEIGHTS ./train_runs/kir_fields/weights/best.pt

# 4. ukur pada dokumen NYATA (before/after)
python scripts/eval_real_docs.py --labels <folder_sampel_nyata>
```

## Kelas yang dideteksi (= kunci field pipeline)

| Jenis | Kelas |
|---|---|
| SIM | nomor_sim, nama, tanggal_lahir, alamat, masa_berlaku, tipe_sim |
| KIR | owner_name, nomor_polisi, nomor_uji, nomor_rangka, nomor_mesin, kubikasi, dimensi, masa_berlaku, tgl_uji |

Kelas cocok persis dengan `CLASS_MAP` di `app/parser/field_detector.py`, jadi
setiap deteksi mengisi slot field yang benar. Detektor **hanya mengisi field
kosong atau mengganti tebakan aturan berkepercayaan-rendah** — nilai yang sudah
diekstrak dari label tak pernah ditimpa (`enrich_with_detector`).

## Hasil terukur pada dokumen NYATA (jujur — hasil negatif)

Detektor dilatih sampai mAP50 **0,995** (validasi sintetis) dan **terbukti
generalisasi ke foto nyata** — smoke-test membaca nama nyata (IRPAN, ROHIM,
WAHYUDIN, OKTA SETIAWAN) dari kartu SIM asli tanpa error dan menolak dengan
anggun (tak mengarang) pada foto sulit.

Tapi diukur pada benchmark **21 dokumen SIM/KIR nyata** (before/after,
`benchmark/accuracy.py`):

| Jenis | Tanpa detektor | Dengan detektor | Nilai salah baru |
|---|---|---|---|
| SIM | 90% | **90%** | 0 |
| KIR | 86% | **86%** | 0 |

**Skor tidak berubah.** Provenance memastikan detektor benar-benar aktif —
tapi hanya menyuplai **1 field** di seluruh set (tanggal lahir yang sudah
ditangkap aturan). Sebabnya, dan ini temuan penting yang jujur:

- Pipeline **aturan + spatial + spec SUDAH menangkap** field yang bisa
  dilokalisasi pada dokumen ini.
- Sisa yang meleset (3 SIM, 5 KIR) **terbatas-pengenalan**: OCR paddle tak
  sanggup membaca pikselnya (blur/silau/rusak). Detektor mengcrop region field
  lalu meng-OCR dengan model paddle **yang sama** → gagal dengan cara yang sama.

Detektor memperbaiki **lokalisasi** ("di mana field"), bukan **pengenalan**
("pixel tak terbaca"). Karena kendala pengikat di sini adalah pengenalan,
detektor tak menggerakkan metrik. **Detektor tidak dipaksa lebih agresif untuk
mengarang angka** — desain aman (isi-kosong + gerbang pola) dipertahankan,
0 regresi.

**Kapan detektor ini berbayar** (kenapa tetap dibangun & di-ship OFF):
- Foto **latar berantakan / miring / multi-dokumen** tempat aturan gagal
  melokalisasi (benchmark saat ini sudah "rapi").
- Setelah **model recognition lebih kuat** dipasang → lokalisasi + recognition
  lebih baik saling menguatkan.
- Setelah **lebih banyak data nyata** terkumpul via standar `/capture` →
  fine-tune ke domain nyata, kecil celah domain.

Di-ship **OFF secara default** (tanpa `FIELD_DETECTOR_SIM/KIR_WEIGHTS` di config
default) — persis seperti STNK/KTP. Menyalakannya tak mengubah perilaku
produksi sampai kendala pengikat diatasi.

## Batas & langkah berikutnya

- **Celah domain**: kartu render ≈ foto nyata, tapi tak identik. Mitigasi:
  augmentasi kuat + validasi pada sampel nyata. Bila sampel nyata bertambah
  (lewat standar foto `/capture` & `/demo/standard`), tambahkan sebagian
  sebagai data latih beranotasi-otomatis (nilai truth → kotak OCR).
- **Prioritas**: SIM sudah 90% tanpa detektor (nilai marginal kecil); KIR 86%
  ruang lebih besar. Detektor ini paling berbayar untuk KIR.
