"""Each route is served once, at its documented path.

Regression: the OCR router (which carries its own /api/v1 prefix) was also
included with prefix="/api/v1", serving /api/v1/api/v1/ocr/*; the monitoring
router was included twice, adding undocumented /metrics/* twins.

Checked through the OpenAPI schema and real requests rather than
app.routes, which does not reflect every include in this app.
"""
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _paths():
    return set(client.get("/openapi.json").json()["paths"])


def test_no_double_prefixed_routes():
    assert not [p for p in _paths() if p.startswith("/api/v1/api/v1")]
    assert client.post("/api/v1/api/v1/ocr/file").status_code == 404


def test_documented_paths_exist():
    paths = _paths()
    for p in ("/api/v1/ocr/file", "/api/v1/verify/document", "/api/v1/metrics/fields", "/api/v1/metrics/health"):
        assert p in paths, p
    assert client.get("/api/v1/metrics/health").status_code == 200


def test_monitoring_has_no_unprefixed_twin():
    assert "/metrics/health" not in _paths()
    assert client.get("/metrics/health").status_code == 404
