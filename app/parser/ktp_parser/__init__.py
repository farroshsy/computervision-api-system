"""
KTP Parser Package

This package contains the modularized KTP parser implementation with separate extractors
for each field in the KTP document.
"""

from .base_extractor import FieldExtractor
from .nik_extractor import NIKExtractor
from .name_extractor import NameExtractor
from .alamat_extractor import AlamatExtractor
from .tempat_lahir_extractor import TempatLahirExtractor
from .tanggal_lahir_extractor import TanggalLahirExtractor
from .gol_darah_extractor import GolDarahExtractor
from .jenis_kelamin_extractor import JenisKelaminExtractor
from .status_perkawinan_extractor import StatusPerkawinanExtractor
from .pekerjaan_extractor import PekerjaanExtractor
from .kewarganegaraan_extractor import KewarganegaraanExtractor
from .berlaku_hingga_extractor import BerlakuHinggaExtractor
from .rt_rw_extractor import RtRwExtractor
from .kelurahan_desa_extractor import KelurahanDesaExtractor
from .kecamatan_extractor import KecamatanExtractor
from .agama_extractor import AgamaExtractor
from .ktp_parser import KTPParser, parse_ktp_fields


__all__ = [
    'FieldExtractor',
    'NIKExtractor',
    'NameExtractor',
    'AlamatExtractor',
    'TempatLahirExtractor',
    'TanggalLahirExtractor',
    'GolDarahExtractor',
    'JenisKelaminExtractor',
    'RtRwExtractor',
    'KelurahanDesaExtractor',
    'KecamatanExtractor',
    'AgamaExtractor',
    'StatusPerkawinanExtractor',
    'PekerjaanExtractor',
    'KewarganegaraanExtractor',
    'BerlakuHinggaExtractor',
    'KTPParser',
    'parse_ktp_fields',
]
