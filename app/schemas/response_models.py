"""Pydantic response models for parsed OCR outputs.
These models are additive and do not change existing OCRResponse to avoid breaking clients/tests.
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, ConfigDict


class ParsedField(BaseModel):
    """A single extracted field with confidence and optional provenance."""
    value: Optional[str] = Field(default=None, description="Normalized field value")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Extractor confidence")
    provenance: Optional[Dict[str, Any]] = Field(default=None, description="Optional metadata about how value was derived")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "value": "JOHN DOE",
                "confidence": 0.94,
                "provenance": {"source": "NameExtractor"}
            }
        }
    )


# -----------------------------
# Per-document field schemas
# Non-breaking: these are not yet wired to responses
# -----------------------------

class SIMFieldsModel(BaseModel):
    """Expected SIM fields with optional presence and ParsedField typing. Extras allowed."""
    nomor_sim: Optional[ParsedField] = None
    nama: Optional[ParsedField] = None
    alamat: Optional[ParsedField] = None
    gol_darah: Optional[ParsedField] = None
    berlaku_hingga: Optional[ParsedField] = None
    tempat_tanggal_lahir: Optional[ParsedField] = None
    jenis_kelamin: Optional[ParsedField] = None
    kewarganegaraan: Optional[ParsedField] = None
    kategori: Optional[ParsedField] = None

    model_config = ConfigDict(extra="allow")


class STNKFieldsModel(BaseModel):
    """Expected STNK fields. Extras allowed."""
    nomor_polisi: Optional[ParsedField] = None
    nama_pemilik: Optional[ParsedField] = None
    alamat: Optional[ParsedField] = None
    merek: Optional[ParsedField] = None
    tipe: Optional[ParsedField] = None
    tahun: Optional[ParsedField] = None
    warna: Optional[ParsedField] = None
    nomor_rangka: Optional[ParsedField] = None
    nomor_mesin: Optional[ParsedField] = None
    masa_berlaku_pajak: Optional[ParsedField] = None
    bbnkb: Optional[ParsedField] = None

    model_config = ConfigDict(extra="allow")


class KIRFieldsModel(BaseModel):
    """Expected KIR fields. Extras allowed."""
    nomor_sertifikat: Optional[ParsedField] = None
    berlaku_sampai: Optional[ParsedField] = None
    nomor_polisi: Optional[ParsedField] = None
    jenis_kendaraan: Optional[ParsedField] = None
    merek_tipe: Optional[ParsedField] = None
    tahun_pembuatan: Optional[ParsedField] = None
    nomor_rangka: Optional[ParsedField] = None
    nomor_mesin: Optional[ParsedField] = None

    model_config = ConfigDict(extra="allow")


class ParsedPayload(BaseModel):
    """Standardized payload returned inside OCRResponse.data."""
    raw_text: List[str] = Field(default_factory=list, description="OCR lines used for parsing")
    fields: Dict[str, ParsedField | str | None] = Field(
        default_factory=dict,
        description="Parsed fields (structured ParsedField when available; plain string for legacy)"
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "raw_text": ["NIK : 3175...", "Nama : JOHN DOE"],
                "fields": {
                    "nik": {"value": "3175...", "confidence": 0.99},
                    "nama": {"value": "JOHN DOE", "confidence": 0.95},
                    "alamat": "JL. MERDEKA NO.45"
                }
            }
        }
    )


class ParsedDocument(BaseModel):
    """High-level document result model useful for downstream consumers."""
    document_type: str = Field(..., description="KTP|SIM|STNK|KIR")
    data: ParsedPayload = Field(..., description="Parsed payload")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "document_type": "KTP",
                "data": ParsedPayload.model_config["json_schema_extra"]["example"]
            }
        }
    )
