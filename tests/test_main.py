from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)
 
def test_read_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "OCR API is running"} 

def test_demo_console_and_evidence_routes():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    r = client.get("/demo")
    assert r.status_code == 200
    assert "Konsol" in r.text and "/demo/evidence" in r.text
    # evidence route serves the runtime file when present, otherwise a
    # friendly Indonesian instructions page — never a bare error
    r2 = client.get("/demo/evidence")
    assert r2.status_code in (200, 404)
    assert ("Tahapan pipeline" in r2.text) or ("Berkas belum tersedia" in r2.text)
