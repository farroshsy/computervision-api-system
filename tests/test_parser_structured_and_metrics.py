import os
from typing import Dict, Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.parser.ktp_parser.ktp_parser import KTPParser
from app.parser.ktp_parser.kelurahan_desa_extractor import KelurahanDesaExtractor
from app.models.schemas import ParserContext


def test_parser_returns_structured_output_and_extractor_legacy_shape(monkeypatch):
    # Direct extractor call should return plain string (legacy)
    ext = KelurahanDesaExtractor()
    legacy = ext.extract(
        ParserContext(
            raw_lines=["KEL/DESA Tanah Abang"],
            extracted_fields={},
            debug=False,
            strict_admin_filter=True,
            enforce_vowel_check=False,
            allow_standalone_address=True,
            allow_standalone_kelurahan=True,
            structured_output=False,
        )
    )
    assert isinstance(legacy, str)
    assert legacy == "TANAH ABANG"

    # Parser.parse should return structured dicts for fields when provenance is enabled
    monkeypatch.setattr(settings, 'RESPONSE_INCLUDE_PROVENANCE', True, raising=False)
    parser = KTPParser()
    result = parser.parse(["NIK 1234567890123456", "NAMA JOHN DOE", "KEL/DESA Tanah Abang"])  # minimal lines
    assert isinstance(result, dict)
    kd = result.get('kelurahan_desa')
    assert isinstance(kd, dict)
    assert set(['value', 'confidence', 'provenance']).issubset(kd.keys())
    assert kd['value'] == 'TANAH ABANG'
    assert isinstance(kd['confidence'], float) and 0.0 <= kd['confidence'] <= 1.0
    assert isinstance(kd['provenance'], dict)


def test_field_metrics_endpoint_exposes_data():
    # Ensure default metrics key is set
    os.environ.setdefault('METRICS_API_KEY', 'default-metrics-key')

    client = TestClient(app)

    # Call endpoint; it requires Bearer auth
    r = client.get(
        "/api/v1/metrics/fields",
        headers={"Authorization": "Bearer default-metrics-key"},
    )
    assert r.status_code == 200
    data: Dict[str, Any] = r.json()
    assert isinstance(data, dict)
    # Keys may vary depending on prior tests; ensure structure is mapping of field->stats dicts
    for k, v in data.items():
        assert isinstance(k, str)
        assert isinstance(v, dict)
        # Check a few expected keys in stats
        for key in ['total', 'success', 'missing', 'below_threshold', 'relaxed_used', 'avg_confidence', 'reasons']:
            assert key in v
