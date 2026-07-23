from fastapi.testclient import TestClient
from app.main import app
import io

client = TestClient(app)
 
def test_ocr_endpoint():
    dummy_file = io.BytesIO(b"fake image data")
    response = client.post("/ocr/testdoc", files={"image": ("test.png", dummy_file, "image/png")})
    assert response.status_code == 200
    assert response.json()["doc_type"] == "testdoc" 