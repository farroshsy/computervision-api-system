"""Auth middleware must protect the API when REQUIRE_API_KEY is on.

Regression: "/" sat in a prefix-matched exclusion list, and every path starts
with "/", so no request was ever authenticated.
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import settings
from app.middleware.auth_middleware import AuthMiddleware


def _client(monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_API_KEY", True)
    monkeypatch.setattr(settings, "API_KEY", "secret")
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/")
    def root():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"ok": True}

    @app.post("/api/v1/ocr/file")
    def ocr():
        return {"ok": True}

    return TestClient(app)


def test_api_route_rejects_missing_key(monkeypatch):
    assert _client(monkeypatch).post("/api/v1/ocr/file").status_code == 401


def test_api_route_rejects_wrong_key(monkeypatch):
    r = _client(monkeypatch).post("/api/v1/ocr/file", headers={"X-API-Key": "nope"})
    assert r.status_code == 401


def test_api_route_accepts_correct_key(monkeypatch):
    r = _client(monkeypatch).post("/api/v1/ocr/file", headers={"X-API-Key": "secret"})
    assert r.status_code == 200


def test_root_and_health_stay_public(monkeypatch):
    c = _client(monkeypatch)
    assert c.get("/").status_code == 200
    assert c.get("/health").status_code == 200
