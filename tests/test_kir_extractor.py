import pytest

from app.parser.kir_parser.kir_extractor import KIRExtractor
from app.models.schemas import ParserContext


def test_kir_basic_fields():
    ext = KIRExtractor()
    lines = [
        "NOMOR UJI: KIR-2024-000123",
        "NO. KENDARAAN: B 1234 XYZ",
        "TANGGAL UJI: 15/08/2024",
        "BERLAKU S/D: 15/08/2025",
        "DITERBITKAN OLEH: Dinas Perhubungan Jakarta",
    ]
    ctx = ParserContext(raw_lines=lines, debug=False)
    res = ext.parse(ctx)
    assert res["document_type"] == "KIR"
    f = res["fields"]
    assert f["certificate_number"]["value"] == "KIR-2024-000123"
    assert f["vehicle_id"]["value"] == "B 1234 XYZ"
    assert f["inspection_date"]["value"] == "15-08-2024"
    assert f["valid_until"]["value"] == "15-08-2025"
    assert "Dinas Perhubungan" in f["issuer"]["value"]


def test_kir_real_card_labels_and_month_name_date():
    # Mirrors a real "KARTU UJI BERKALA KENDARAAN BERMOTOR" card layout
    ext = KIRExtractor()
    lines = [
        "KARTU UJI BERKALA KENDARAAN BERMOTOR",
        "Nama pemilik : SOEGIHARTO",
        "Nomor registrasi kendaraan : N 8357 UR",
        "Nomor rangka kendaraan : FT418V550967",
        "Nomor motor penggerak : 6D22204922",
        "Nomor uji kendaraan : TBN5380",
        "Masa berlaku uji berkala : 26 JULI 2023",
        "LULUS UJI BERKALA",
    ]
    ctx = ParserContext(raw_lines=lines, debug=False)
    res = ext.parse(ctx)
    f = res["fields"]
    assert f["owner_name"]["value"] == "SOEGIHARTO"
    assert f["vehicle_id"]["value"] == "N 8357 UR"
    assert f["nomor_rangka"]["value"] == "FT418V550967"
    assert f["nomor_mesin"]["value"] == "6D22204922"
    assert f["certificate_number"]["value"] == "TBN5380"
    assert f["valid_until"]["value"] == "26-07-2023"


def test_kir_month_name_date_all_months():
    ext = KIRExtractor()
    for name, mm in (("JANUARI", 1), ("MEI", 5), ("AGUSTUS", 8), ("DESEMBER", 12)):
        ctx = ParserContext(raw_lines=[f"MASA BERLAKU : 5 {name} 2026"], debug=False)
        res = ext.parse(ctx)
        assert res["fields"]["valid_until"]["value"] == f"05-{mm:02d}-2026", name


def test_kir_english_month_abbreviations():
    # Some KIR offices print English abbreviations: "13 AUG 2023"
    ext = KIRExtractor()
    for name, mm in (("AUG", 8), ("JUN", 6), ("OCT", 10), ("DEC", 12)):
        ctx = ParserContext(raw_lines=[f"MASA BERLAKU UJI BERKALA : 13 {name} 2023"], debug=False)
        res = ext.parse(ctx)
        assert res["fields"]["valid_until"]["value"] == f"13-{mm:02d}-2023", name


def test_kir_glued_ocr_date_recovered_without_label():
    # Real OCR output: the label vanished, date glued with G->C confusion
    ext = KIRExtractor()
    ctx = ParserContext(raw_lines=["LULUSUJIBERKALA", "13AUC2023", "penguji"], debug=False)
    res = ext.parse(ctx)
    assert res["fields"]["valid_until"]["value"] == "13-08-2023"
    # and the glued date must NOT be misread as an engine number
    assert res["fields"].get("nomor_mesin", {}).get("value") != "13AUC2023"


def test_kir_value_shape_fallback():
    # Labels garbled beyond recognition; values keep their shapes
    ext = KIRExtractor()
    ctx = ParserContext(raw_lines=[
        "merungoSandaran",           # was: Nomor rangka kendaraan
        "MHKB3BA1JHK046896",
        "pcyd",                      # was: Nomor uji kendaraan
        "BKS52302A",
        "Nomopeggera",               # was: Nomor motor penggerak
        "K3MH09391",
    ], debug=False)
    res = ext.parse(ctx)
    f = res["fields"]
    assert f["nomor_rangka"]["value"] == "MHKB3BA1JHK046896"
    assert f["certificate_number"]["value"] == "BKS52302A"
    assert f["nomor_mesin"]["value"] == "K3MH09391"


def test_kir_glued_label_matches():
    ext = KIRExtractor()
    ctx = ParserContext(raw_lines=["NAMAPEMILIK", "PT SERASI AUTORAYA"], debug=False)
    res = ext.parse(ctx)
    assert res["fields"]["owner_name"]["value"] == "PT SERASI AUTORAYA"



def test_kir_logistics_fields_from_real_scan():
    # Lines transcribed from a real clean KIR scan (DRS H. BARKATI card)
    ext = KIRExtractor()
    ctx = ParserContext(raw_lines=[
        "KARTU UJI BERKALA KENDARAAN BERMOTOR",
        "Nama pemilik : DRS H. BARKATI",
        "Nomor registrasi kendaraan : DA8545TFA",
        "Nomor rangka kendaraan : MHMFE74P48K011538",
        "Nomor motor penggerak : 4D34TD21878",
        "Nomor uji kendaraan : BBO41642201",
        "Merek/tipe : MITSUBISHI / FE 74 HDV",
        "Tahun pembuatan/perakitan : 2008",
        "Berat kosong kendaraan : 3420 kg",
        "JBB/JBKB : 7500 kg / 0 kg",
        "Daya angkut (orang/kg) : 180 orang / 3900 kg",
        "Kelas jalan terendah yang boleh dilalui : III",
        "Masa berlaku uji berkala : 08 JANUARI 2022",
        "LULUS UJI BERKALA",
    ], debug=False)
    res = ext.parse(ctx)
    f = res["fields"]
    assert f["vehicle_id"]["value"] == "DA8545TFA"
    assert f["nomor_rangka"]["value"] == "MHMFE74P48K011538"
    assert f["nomor_mesin"]["value"] == "4D34TD21878"
    assert f["certificate_number"]["value"] == "BBO41642201"
    assert f["valid_until"]["value"] == "08-01-2022"
    assert f["merek_tipe"]["value"] == "MITSUBISHI / FE 74 HDV"
    assert f["tahun_pembuatan"]["value"] == "2008"
    assert f["berat_kosong_kg"]["value"] == "3420"
    assert f["jbb_kg"]["value"] == "7500"
    assert f["daya_angkut_orang"]["value"] == "180"
    assert f["daya_angkut_kg"]["value"] == "3900"
    assert f["kelas_jalan"]["value"] == "III"
    assert f["owner_name"]["value"] == "DRS H. BARKATI"
