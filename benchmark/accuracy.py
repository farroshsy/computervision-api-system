#!/usr/bin/env python3
"""Accuracy against human ground truth — the only measure that means anything.

Every extracted value falls into exactly one bucket:

  CORRECT          value matches the document
  WRONG            value does not match  <-- the dangerous bucket: a plausible
                                             wrong value is never reviewed
  MISSED           truth has a value, we returned nothing (-> needs_review, safe)
  CORRECTLY_ABSENT truth has nothing, we returned nothing
  HALLUCINATED     truth has nothing, we returned something  <-- also dangerous

Coverage counts CORRECT + WRONG + HALLUCINATED together. That is why coverage
alone said "Dimensi 100%" while every single value was the cargo tub.
"""
import json, pathlib, re, sys
from collections import defaultdict

HERE = pathlib.Path(__file__).parent
TRUTH = HERE / "truth"

# spec requirement -> (truth key, [candidate API keys])
# Field list taken from the customer's own deck ("15082023 Google Cloud Ace _
# Logisly OCR"), which numbers and boxes each wanted field on a photo of the
# document. Two of theirs were never being scored (KTP "ID registration place",
# STNK "Type of registration") and one we DID score — STNK Warna — is not on
# their list at all. Grading against our own list instead of theirs is how you
# report a number nobody asked for.
SPEC = {
    "KTP": {
        "ID (NIK)":     ("nik",            ["nik"]),
        "Name":         ("nama",           ["nama", "name"]),
        "Date of birth":("tanggal_lahir",  ["tanggal_lahir"]),
        "Sex type":     ("jenis_kelamin",  ["jenis_kelamin"]),
        # spec item 5: the "PROVINSI …" / "KABUPATEN …" header
        "Reg. province":("provinsi",       ["provinsi"]),
        "Reg. city":    ("kota",           ["kota"]),
    },
    "SIM": {
        "Type of DL":   ("tipe_sim",       ["tipe_sim", "class"]),
        "DL Number":    ("nomor_sim",      ["sim_number", "id_number"]),
        "Expiration":   ("masa_berlaku",   ["expiry_date", "masa_berlaku"]),
    },
    "STNK": {
        "Plate":        ("nomor_polisi",   ["nomor_polisi", "plate_number"]),
        "Truck's type": ("model",          ["model"]),
        "Car's year":   ("tahun_pembuatan",["year", "tahun_pembuatan"]),
        # The STNK card's own expiry. On a photo that also shows the annual tax
        # receipt, `tax_valid_to` is the RECEIPT's date — a different, also-true
        # date — so it may only stand in when the card's own field is absent.
        "Expiration":   ("berlaku_sampai", ["berlaku_sampai", "tax_valid_to", "masa_berlaku"]),
        # spec item 5. NOT `warna` — the customer's deck never asks for colour.
        "Type of reg.": ("jenis",          ["jenis", "jenis_registrasi"]),
    },
    "KIR": {
        "Plate":        ("nomor_polisi",   ["nomor_polisi", "vehicle_id"]),
        "Pass/fail":    ("hasil_uji_normalized", ["hasil_uji_normalized"]),
        "Expiration":   ("masa_berlaku",   ["masa_berlaku", "valid_until"]),
        "Dimensi":      ("dimensi",        ["dimensi"]),
        "Kubikasi":     ("kubikasi",       ["kubikasi"]),
    },
}


def norm(s):
    """Compare on content, not punctuation: OCR and humans differ on spacing,
    separators, thousands commas and unit suffixes. None of that is an accuracy
    failure, and grading it as one would overstate the error rate."""
    s = str(s or "").upper()
    s = re.sub(r"(MM|CC|CM3)\b", "", s)      # no leading \b: "7790CC" is one token
    return re.sub(r"[^A-Z0-9]", "", s)


_MONTHS = {
    "JAN": 1, "JANUARI": 1, "JANUARY": 1, "FEB": 2, "PEB": 2, "FEBRUARI": 2,
    "FEBRUARY": 2, "MAR": 3, "MARET": 3, "MARCH": 3, "APR": 4, "APRIL": 4,
    "MEI": 5, "MAY": 5, "JUN": 6, "JUNI": 6, "JUNE": 6, "JUL": 7, "JULI": 7,
    "JULY": 7, "AGU": 8, "AGT": 8, "AGUSTUS": 8, "AUG": 8, "AUGUST": 8,
    "AUC": 8, "SEP": 9, "SEPT": 9, "SEPTEMBER": 9, "OKT": 10, "OCT": 10,
    "OKTOBER": 10, "OCTOBER": 10, "NOV": 11, "NOVEMBER": 11, "DES": 12,
    "DEC": 12, "DESEMBER": 12, "DECEMBER": 12,
}


def norm_date(s):
    """Both sides mean the same day whether written 13-08-2023, 2023-08-13 or
    '13 AUG 2023'. Only a different DAY is an error."""
    t = str(s or "").upper()
    m = re.search(r"(\d{1,2})\s*([A-Z]{3,9})\s*(\d{4})", t)
    if m and m.group(2) in _MONTHS:
        return f"{int(m.group(1)):02d}-{_MONTHS[m.group(2)]:02d}-{m.group(3)}"
    d = re.findall(r"\d+", t)
    if len(d) == 3:
        a, b, c = d
        if len(a) == 4:          # YYYY-MM-DD -> DD-MM-YYYY
            a, c = c, a
        return f"{int(a):02d}-{int(b):02d}-{c}"
    return norm(s)


def val(fields, keys):
    for k in keys:
        f = fields.get(k)
        v = f.get("value") if isinstance(f, dict) else f
        if v not in (None, "", []):
            return v
    return None


def load(dirname):
    """source filename -> {doc_type: fields}. MULTI flattened."""
    out = defaultdict(dict)
    d = HERE / dirname
    for p in d.glob("*.json"):
        j = json.loads(p.read_text(encoding="utf-8"))
        if "_error" in j:
            continue
        src = pathlib.Path(j.get("_source", "")).name
        if j.get("documents"):
            for sub in j["documents"]:
                out[src][sub.get("document_type")] = (sub.get("data") or {}).get("fields") or {}
        else:
            out[src][j.get("document_type")] = (j.get("data") or {}).get("fields") or {}
    return out


def score(dirname):
    got = load(dirname)
    tally = defaultdict(lambda: defaultdict(int))
    detail = defaultdict(list)
    for dt, spec in SPEC.items():
        tf = TRUTH / f"{dt}.json"
        if not tf.exists():
            continue
        truth = json.loads(tf.read_text(encoding="utf-8"))
        for fname, t in truth.items():
            if fname.startswith("_"):
                continue
            fields = got.get(fname, {}).get(dt, {})
            for req, (tkey, keys) in spec.items():
                tv = t.get(tkey)
                gv = val(fields, keys)
                n = norm_date if "ate" in req or "xpir" in req else norm
                if tv in (None, "") and gv in (None, ""):
                    b = "CORRECTLY_ABSENT"
                elif tv in (None, ""):
                    b = "HALLUCINATED"
                elif gv in (None, ""):
                    b = "MISSED"
                elif n(tv) == n(gv):
                    b = "CORRECT"
                else:
                    b = "WRONG"
                tally[dt][b] += 1
                if b in ("WRONG", "HALLUCINATED"):
                    detail[dt].append(f"{fname[:26]:28} {req:14} truth={str(tv)[:22]!r:24} got={str(gv)[:22]!r}")
    return tally, detail


def main():
    a, da = score("results")
    b, db = score("results_v5")
    BUCKETS = ["CORRECT", "WRONG", "HALLUCINATED", "MISSED", "CORRECTLY_ABSENT"]

    print("=" * 78)
    print("ACCURACY vs HUMAN GROUND TRUTH")
    print("=" * 78)
    for dt in SPEC:
        if not (a[dt] or b[dt]):
            continue
        print(f"\n### {dt}")
        print(f"  {'bucket':18} {'v1':>6} {'v2':>6}")
        for k in BUCKETS:
            print(f"  {k:18} {a[dt][k]:6} {b[dt][k]:6}")
        for tag, t in (("v1", a[dt]), ("v2", b[dt])):
            gradable = t["CORRECT"] + t["WRONG"] + t["MISSED"] + t["HALLUCINATED"]
            acc = 100 * t["CORRECT"] / gradable if gradable else 0
            harm = t["WRONG"] + t["HALLUCINATED"]
            print(f"  -> {tag}: {acc:.0f}% correct, {harm} actively wrong value(s)")

    print("\n" + "=" * 78)
    print("THE DANGEROUS BUCKET — wrong / hallucinated values still in v2")
    print("=" * 78)
    tot = 0
    for dt in SPEC:
        if db[dt]:
            print(f"\n  {dt}:")
            for line in sorted(db[dt]):
                print("    " + line)
            tot += len(db[dt])
    print(f"\n  total in v2: {tot}   (v1 had {sum(len(v) for v in da.values())})")


if __name__ == "__main__":
    main()
