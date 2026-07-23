from typing import Optional
from pydantic import BaseModel, Field

class SIMDocument(BaseModel):
    id_number: Optional[str] = Field(default=None, description="SIM ID/number")
    name: Optional[str] = Field(default=None, description="Holder name")
    address: Optional[str] = Field(default=None, description="Holder address")
    expiry_date: Optional[str] = Field(default=None, description="Valid until (DD-MM-YYYY)")

class STNKDocument(BaseModel):
    nomor_polisi: Optional[str] = Field(default=None, description="License plate number")
    owner: Optional[str] = Field(default=None, description="Owner name")
    alamat: Optional[str] = Field(default=None, description="Owner address")
    nomor_rangka: Optional[str] = Field(default=None, description="VIN/Chassis number")
    nomor_mesin: Optional[str] = Field(default=None, description="Engine number")

class KIRDocument(BaseModel):
    nomor_rangka: Optional[str] = Field(default=None, description="VIN/Chassis number")
    nomor_mesin: Optional[str] = Field(default=None, description="Engine number")
    masa_berlaku: Optional[str] = Field(default=None, description="Valid until (DD-MM-YYYY)")
    tgl_uji: Optional[str] = Field(default=None, description="Inspection date (DD-MM-YYYY)")
