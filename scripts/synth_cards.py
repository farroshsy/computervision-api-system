"""Synthetic labelled cards for training SIM & KIR field detectors.

The problem: to train a YOLO-OBB field detector we need images WITH per-field
bounding boxes. Our real corpus has ~10 photos per type and only TEXT ground
truth (what the value is, not where it sits). Hand-drawing boxes on scraped
photos is the bottleneck — and scraping real Indonesian IDs is a PII/copyright
problem for a production KYC pitch.

The fix, grounded in the fact that SIM (Polri new format, 1 Jul 2024) and KIR
(national inspection card) have FIXED layouts: render synthetic cards from the
public layout with fake-but-valid values at KNOWN positions. Because we PLACE
each field, its box is exact and free — including the hard fields OCR can't
read. Heavy augmentation (perspective, lighting, blur, noise, backgrounds)
makes them look like phone photos.

Honesty line: synthetic data is used only to LEARN where fields sit. Accuracy
is always MEASURED on the real 10-11 samples, held out, never trained on.

Output is Roboflow-compatible (train/valid/test + data.yaml), so it feeds the
same `yolo obb train` path that produced the STNK/KTP detectors.

    python scripts/synth_cards.py --type SIM --n 1500 --out ./train_runs/data/sim_synth
    python scripts/synth_cards.py --type KIR --n 1500 --out ./train_runs/data/kir_synth
"""
import argparse
import random
import string
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent

# Reuse the REAL closed set of plate regions the parser validates against, so
# synthetic plates are drawn from the same distribution the system accepts.
try:
    import sys
    sys.path.insert(0, str(ROOT))
    from app.parser.spec_fields import _PLATE_REGIONS
    PLATE_REGIONS = sorted(_PLATE_REGIONS)
except Exception:
    PLATE_REGIONS = ["B", "D", "F", "AB", "AD", "AG", "L", "N", "BK", "BM", "KT", "DK"]

# ---- fonts -----------------------------------------------------------------
_FONT_DIRS = [Path("C:/Windows/Fonts"), Path("/usr/share/fonts"), Path("/Library/Fonts")]


def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    for d in _FONT_DIRS:
        p = d / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    # search recursively as a fallback (Linux ships fonts in subdirs)
    for d in _FONT_DIRS:
        if d.exists():
            hits = list(d.rglob(name))
            if hits:
                return ImageFont.truetype(str(hits[0]), size)
    return ImageFont.load_default()


def fonts():
    return {
        "reg": lambda s: _font("arial.ttf", s),
        "bold": lambda s: _font("arialbd.ttf", s),
        "black": lambda s: _font("ariblk.ttf", s),
    }


# ---- value pools (fake but shape-valid) ------------------------------------
_FIRST = ["BUDI", "SITI", "AGUS", "DEWI", "RIZKY", "PUTRI", "ANDI", "WAHYU", "FITRI",
          "JOKO", "RATNA", "BAMBANG", "INDAH", "HERI", "MAYA", "FIRDAUS", "VIVIN",
          "ARI", "TRI", "EKO", "NUR", "DIAN", "YUDI", "RINI", "HASAN", "LILIS"]
_LAST = ["SANTOSO", "WIJAYA", "PRATAMA", "NUGROHO", "SUSANTO", "LESTARI", "HARTONO",
         "SAPUTRA", "RAHAYU", "KURNIAWAN", "FEBRIYANTI", "BARKATI", "MAULANA",
         "HIDAYAT", "PERMANA", "ANGGRAINI", "SETIAWAN"]
_CITY = ["JAKARTA", "SURABAYA", "BANDUNG", "SEMARANG", "MEDAN", "MAKASSAR", "BEKASI",
         "DEPOK", "TANGERANG", "MALANG", "BOGOR", "AMUNTAI", "BANTUL", "SLEMAN"]
_JOB = ["KARYAWAN SWASTA", "WIRASWASTA", "PEGAWAI NEGERI", "PELAJAR/MAHASISWA",
        "PENGEMUDI", "PEDAGANG", "PETANI"]
_STREET = ["JL. MERDEKA", "JL. SUDIRMAN", "JL. GAJAH MADA", "JL. P. ANTASARI",
           "JL. DIPONEGORO", "JL. AHMAD YANI", "JL. MELATI"]
_SIM_TYPE = ["A", "B I", "B II", "C", "A UMUM", "B I UMUM"]
_MERK = ["MITSUBISHI / FE 74 HDV", "ISUZU / PHR 54", "HINO / DUTRO 110",
         "TOYOTA / DYNA 130", "MITSUBISHI / COLT DIESEL"]


def _name():
    return f"{random.choice(_FIRST)} {random.choice(_LAST)}"


def _plate():
    reg = random.choice(PLATE_REGIONS)
    return f"{reg} {random.randint(1, 9999)} {''.join(random.choices(string.ascii_uppercase, k=random.randint(1, 3)))}"


def _nik():
    return "".join(random.choices(string.digits, k=16))


def _sim_no():
    return f"{random.randint(1000, 9999)}-{random.randint(1000, 9999)}-{random.randint(0, 999999):06d}"


def _uji_no():
    return f"{random.choice(['BB', 'AB', 'DK', 'KT'])}{random.randint(0, 9)}{random.randint(1000000, 9999999)}"


def _vin():
    return "".join(random.choices("ABCDEFGHJKLMNPRSTUVWXYZ0123456789", k=17))


def _engine():
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=random.randint(8, 12)))


def _date():
    return f"{random.randint(1, 28):02d}-{random.randint(1, 12):02d}-{random.randint(2019, 2027)}"


def _slashdate():
    return f"{random.randint(1, 28):02d}/{random.randint(1, 12):02d}/{random.randint(2022, 2028)}"


def _dims():
    return (random.randint(3800, 9000), random.randint(1500, 2500), random.randint(1600, 3200))


# ---- drawing helpers -------------------------------------------------------
def _box_of(draw, xy, text, font):
    """Tight box (4 corners, px) around `text` drawn at xy with font."""
    l, t, r, b = draw.textbbox(xy, text, font=font)
    pad = 3
    return [[l - pad, t - pad], [r + pad, t - pad], [r + pad, b + pad], [l - pad, b + pad]]


def _labelled(draw, x, y, label, value, font, boxes, cls):
    """Draw 'label value'; box only the value under class id `cls`."""
    draw.text((x, y), label, fill=(20, 20, 30), font=font)
    lw = draw.textlength(label, font=font)
    vx = x + lw
    draw.text((vx, y), value, fill=(15, 15, 25), font=font)
    if cls is not None:
        boxes.append((cls, _box_of(draw, (vx, y), value, font)))


# ---- SIM layout (landscape ID-1, new format) -------------------------------
# class ids: 0 nomor_sim 1 nama 2 tanggal_lahir 3 alamat 4 masa_berlaku 5 tipe_sim
SIM_CLASSES = ["nomor_sim", "nama", "tanggal_lahir", "alamat", "masa_berlaku", "tipe_sim"]


def render_sim(F):
    W, H = 1012, 638
    img = Image.new("RGB", (W, H), (247, 246, 244))
    d = ImageDraw.Draw(img)
    boxes = []

    # header band
    d.rectangle([0, 0, W, 82], fill=(178, 34, 40))
    d.text((150, 14), "INDONESIA", font=F["black"](34), fill=(255, 255, 255))
    d.text((152, 52), "SURAT IZIN MENGEMUDI", font=F["reg"](18), fill=(255, 235, 235))
    d.text((760, 20), "DRIVING LICENSE", font=F["bold"](20), fill=(255, 255, 255))
    # crest placeholder
    d.ellipse([40, 12, 110, 76], fill=(212, 175, 55))

    # golongan (big letter) top-right  -> tipe_sim
    tipe = random.choice(_SIM_TYPE)
    gf = F["black"](64)
    gx, gy = 905, 100
    d.text((gx, gy), tipe.split()[0], font=gf, fill=(20, 20, 30))
    boxes.append((5, _box_of(d, (gx, gy), tipe.split()[0], gf)))
    if "UMUM" in tipe:
        d.text((880, 172), "UMUM", font=F["bold"](18), fill=(60, 60, 60))

    # nomor_sim
    nf = F["bold"](30)
    ns = _sim_no()
    d.text((600, 112), ns, font=nf, fill=(20, 20, 30))
    boxes.append((0, _box_of(d, (600, 112), ns, nf)))

    # photo box
    d.rectangle([40, 150, 250, 470], fill=(205, 205, 210), outline=(150, 150, 150))
    d.rectangle([80, 420, 250, 560], fill=(225, 225, 228))  # ghost photo

    # numbered field column
    ff = F["reg"](26)
    x = 300
    name = _name()
    _labelled(d, x, 190, "1. ", name, ff, boxes, 1)
    city, dob = random.choice(_CITY), _slashdate()
    _labelled(d, x, 232, f"2. {city}, ", dob, ff, boxes, 2)
    d.text((x, 274), f"3. {random.choice(['A','B','O','AB'])} - PRIA", font=ff, fill=(15, 15, 25))
    alamat = f"{random.choice(_STREET)} NO. {random.randint(1, 200)}"
    _labelled(d, x, 316, "4. ", alamat, ff, boxes, 3)
    d.text((x, 358), f"5. {random.choice(_JOB)}", font=ff, fill=(15, 15, 25))
    d.text((x, 400), f"6. {random.choice(_CITY)}", font=ff, fill=(15, 15, 25))

    # masa_berlaku bottom-right
    mf = F["bold"](28)
    mb = _slashdate()
    d.text((770, 500), mb, font=mf, fill=(20, 20, 30))
    boxes.append((4, _box_of(d, (770, 500), mb, mf)))

    return img, boxes


# ---- KIR layout (portrait inspection card) ---------------------------------
# 0 owner_name 1 nomor_polisi 2 nomor_uji 3 nomor_rangka 4 nomor_mesin
# 5 kubikasi 6 dimensi 7 masa_berlaku 8 tgl_uji
KIR_CLASSES = ["owner_name", "nomor_polisi", "nomor_uji", "nomor_rangka",
               "nomor_mesin", "kubikasi", "dimensi", "masa_berlaku", "tgl_uji"]


def render_kir(F):
    W, H = 760, 1075
    img = Image.new("RGB", (W, H), (223, 235, 233))
    d = ImageDraw.Draw(img)
    boxes = []
    reg = F["reg"]
    bold = F["bold"]

    # title
    d.text((150, 26), "KARTU UJI BERKALA KENDARAAN BERMOTOR", font=bold(17), fill=(20, 20, 40))
    d.text((205, 50), "VEHICLE PERIODICAL INSPECTION CARD", font=reg(12), fill=(70, 70, 90))
    d.ellipse([40, 20, 100, 80], outline=(90, 90, 90), width=2)
    d.rectangle([620, 20, 720, 120], outline=(60, 60, 60), width=2)  # QR placeholder

    # identity block (two columns)
    d.rectangle([20, 150, 740, 165], fill=(120, 150, 148))
    d.text((26, 150), "IDENTITAS PEMILIK", font=bold(12), fill=(255, 255, 255))
    d.text((390, 150), "IDENTITAS KENDARAAN", font=bold(12), fill=(255, 255, 255))

    lf = reg(19)
    # left column
    owner = _name()
    _labelled(d, 26, 185, "Nama pemilik  : ", owner, lf, boxes, 0)
    d.text((26, 220), "Alamat  : ", font=lf, fill=(15, 15, 25))
    d.text((26, 245), f"{random.choice(_STREET)} RT {random.randint(1,9):02d}", font=lf, fill=(15, 15, 25))
    d.text((26, 270), random.choice(_CITY), font=lf, fill=(15, 15, 25))
    # right column
    xr = 390
    plate = _plate()
    _labelled(d, xr, 185, "No. registrasi : ", plate, lf, boxes, 1)
    _labelled(d, xr, 215, "No. rangka : ", _vin(), lf, boxes, 3)
    _labelled(d, xr, 245, "No. mesin : ", _engine(), lf, boxes, 4)
    _labelled(d, xr, 275, "No. uji : ", _uji_no(), lf, boxes, 2)

    # four-photo strip (decoy region the detector must NOT confuse for fields)
    d.rectangle([20, 320, 740, 430], fill=(235, 240, 238), outline=(150, 150, 150))
    for i in range(4):
        d.rectangle([30 + i * 178, 335, 190 + i * 178, 420], fill=(180, 180, 175))

    # technical spec block
    d.rectangle([20, 455, 740, 470], fill=(120, 150, 148))
    d.text((26, 455), "SPESIFIKASI TEKNIS KENDARAAN BERMOTOR", font=bold(12), fill=(255, 255, 255))
    sf = reg(19)
    d.text((26, 490), f"Jenis : MOBIL BARANG BAK TERBUKA", font=sf, fill=(15, 15, 25))
    d.text((26, 520), f"Merk/tipe : {random.choice(_MERK)}", font=sf, fill=(15, 15, 25))
    _labelled(d, 26, 550, "Isi silinder : ", f"{random.randint(1500,4000)} cc", sf, boxes, 5)

    # dimensi (P x L x T) — box the whole numeric span
    p, l, t = _dims()
    dim_label = "Dimensi utama : "
    d.text((26, 585), dim_label, font=sf, fill=(15, 15, 25))
    dvx = 26 + d.textlength(dim_label, font=sf)
    dim_val = f"Panjang {p}  Lebar {l}  Tinggi {t} mm"
    d.text((dvx, 585), dim_val, font=sf, fill=(15, 15, 25))
    boxes.append((6, _box_of(d, (dvx, 585), dim_val, sf)))

    _labelled(d, 26, 620, "Masa berlaku uji : ", _date(), sf, boxes, 7)
    _labelled(d, 26, 650, "Tanggal uji : ", _date(), sf, boxes, 8)

    # footer strip
    d.rectangle([20, 980, 740, 1055], outline=(150, 150, 150))
    d.text((26, 990), f"NOMOR REGISTRASI : {plate}", font=reg(16), fill=(40, 40, 60))

    return img, boxes


RENDERERS = {"SIM": (render_sim, SIM_CLASSES), "KIR": (render_kir, KIR_CLASSES)}


# ---- augmentation: photo-like variation ------------------------------------
def _background(w, h):
    base = np.array([random.randint(30, 210) for _ in range(3)], dtype=np.float32)
    tint = np.array([random.randint(-20, 20) for _ in range(3)], dtype=np.float32)
    grad = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    canvas = base[None, None, :] + grad * tint[None, None, :]
    canvas = np.clip(canvas, 0, 255).astype(np.uint8)
    canvas = np.repeat(canvas, w, axis=1) if canvas.shape[1] == 1 else canvas
    if canvas.shape[1] != w:
        canvas = np.tile(canvas, (1, w, 1))[:, :w]
    noise = np.random.normal(0, 6, canvas.shape).astype(np.float32)
    return np.clip(canvas.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def augment(card: Image.Image, boxes):
    cw, ch = card.size
    # canvas larger than card so perspective has room
    scale = random.uniform(0.62, 0.9)
    Wc = int(cw / scale * random.uniform(1.0, 1.15))
    Hc = int(ch / scale * random.uniform(1.0, 1.15))
    canvas = _background(Wc, Hc)

    # place card
    s = random.uniform(0.8, 1.0)
    dw, dh = int(cw * s), int(ch * s)
    ox = random.randint(0, max(1, Wc - dw))
    oy = random.randint(0, max(1, Hc - dh))
    card_r = card.resize((dw, dh))
    canvas_img = Image.fromarray(canvas)
    canvas_img.paste(card_r, (ox, oy))
    canvas = np.array(canvas_img)

    # field corners into canvas space
    pts = []
    for cls, corners in boxes:
        for (px, py) in corners:
            pts.append([px / cw * dw + ox, py / ch * dh + oy])
    pts = np.array(pts, dtype=np.float32).reshape(-1, 1, 2)

    # perspective warp of the whole canvas
    src = np.array([[0, 0], [Wc, 0], [Wc, Hc], [0, Hc]], dtype=np.float32)
    jx, jy = Wc * 0.09, Hc * 0.09
    dst = src + np.array([[random.uniform(0, jx), random.uniform(0, jy)],
                          [random.uniform(-jx, 0), random.uniform(0, jy)],
                          [random.uniform(-jx, 0), random.uniform(-jy, 0)],
                          [random.uniform(0, jx), random.uniform(-jy, 0)]], dtype=np.float32)
    Hm = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(canvas, Hm, (Wc, Hc), borderMode=cv2.BORDER_REFLECT)
    pts_w = cv2.perspectiveTransform(pts, Hm).reshape(-1, 4, 2)

    # photometric
    im = Image.fromarray(out)
    im = ImageEnhance.Brightness(im).enhance(random.uniform(0.72, 1.18))
    im = ImageEnhance.Contrast(im).enhance(random.uniform(0.82, 1.2))
    im = ImageEnhance.Color(im).enhance(random.uniform(0.7, 1.2))
    if random.random() < 0.6:
        im = im.filter(ImageFilter.GaussianBlur(random.uniform(0.3, 1.3)))
    arr = np.array(im).astype(np.float32)
    arr += np.random.normal(0, random.uniform(2, 9), arr.shape)
    im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    # label lines (normalised, clipped)
    lines = []
    for (cls, _), quad in zip(boxes, pts_w):
        q = quad.copy()
        q[:, 0] = np.clip(q[:, 0] / Wc, 0, 1)
        q[:, 1] = np.clip(q[:, 1] / Hc, 0, 1)
        if q[:, 0].ptp() < 0.005 or q[:, 1].ptp() < 0.005:
            continue
        lines.append(f"{cls} " + " ".join(f"{v:.6f}" for v in q.flatten()))
    return im, lines


def write_split(doc_type, n, out_dir, jpeg=True):
    render, classes = RENDERERS[doc_type]
    F = fonts()
    out = Path(out_dir)
    for split in ("train", "valid", "test"):
        (out / split / "images").mkdir(parents=True, exist_ok=True)
        (out / split / "labels").mkdir(parents=True, exist_ok=True)

    n_val = max(1, int(n * 0.12))
    n_test = max(1, int(n * 0.08))
    for i in range(n):
        split = "train" if i < n - n_val - n_test else ("valid" if i < n - n_test else "test")
        card, boxes = render(F)
        im, lines = augment(card, boxes)
        stem = f"{doc_type.lower()}_{i:05d}"
        ext = "jpg" if jpeg else "png"
        q = random.randint(45, 92) if jpeg else None
        im.convert("RGB").save(out / split / "images" / f"{stem}.{ext}",
                               quality=q) if jpeg else im.save(out / split / "images" / f"{stem}.{ext}")
        (out / split / "labels" / f"{stem}.txt").write_text("\n".join(lines), encoding="utf-8")
        if (i + 1) % 200 == 0:
            print(f"  {doc_type}: {i + 1}/{n}")

    names = "\n".join(f"  {i}: {c}" for i, c in enumerate(classes))
    (out / "data.yaml").write_text(
        f"train: train/images\nval: valid/images\ntest: test/images\n\nnames: \n{names}\n",
        encoding="utf-8")
    print(f"{doc_type}: wrote {n} images -> {out}  ({len(classes)} classes)")
    return out / "data.yaml"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", required=True, choices=["SIM", "KIR"])
    ap.add_argument("--n", type=int, default=1500)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--preview", type=int, default=0,
                    help="also dump N debug images with boxes drawn, to <out>/_preview")
    args = ap.parse_args()
    random.seed(args.seed)
    np.random.seed(args.seed)

    if args.preview:
        _dump_preview(args.type, args.preview, Path(args.out) / "_preview")
        return 0
    write_split(args.type, args.n, args.out)
    return 0


def _dump_preview(doc_type, n, out):
    """Render a few images with boxes overlaid, to eyeball that labels align."""
    render, classes = RENDERERS[doc_type]
    F = fonts()
    out.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        card, boxes = render(F)
        im, lines = augment(card, boxes)
        arr = np.array(im.convert("RGB"))
        Wc, Hc = im.size
        for ln in lines:
            parts = ln.split()
            cls = int(parts[0])
            pts = np.array([float(x) for x in parts[1:]], dtype=np.float32).reshape(4, 2)
            pts[:, 0] *= Wc
            pts[:, 1] *= Hc
            cv2.polylines(arr, [pts.astype(np.int32)], True, (0, 200, 0), 2)
            cv2.putText(arr, classes[cls], tuple(pts[0].astype(int)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        cv2.imwrite(str(out / f"preview_{doc_type.lower()}_{i}.png"), cv2.cvtColor(arr, cv2.COLOR_RGB2BGR))
    print(f"preview: {n} images -> {out}")


if __name__ == "__main__":
    raise SystemExit(main())
