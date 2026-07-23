"""Test error handling and response formats for the OCR API."""
import pytest
from fastapi.testclient import TestClient
from fastapi import status
from app.main import app
from unittest.mock import patch, MagicMock
import io
import json

client = TestClient(app)

def test_404_not_found():
    """Test that a 404 response returns the expected format."""
    response = client.get("/non-existent-endpoint")
    assert response.status_code == status.HTTP_404_NOT_FOUND
    
    # Check response format matches FastAPI's default
    error_data = response.json()
    assert "detail" in error_data
    assert error_data["detail"] == "Not Found"

def test_invalid_file_upload():
    """Test file upload with invalid file type."""
    # Test with invalid file type - FastAPI will return 400 for invalid MIME type
    dummy_file = io.BytesIO(b"fake image data")
    response = client.post(
        "/api/v1/ocr/file",
        files={"file": ("test.txt", dummy_file, "text/plain")},
        data={"document_type": "KTP"}
    )
    
    # FastAPI returns 400 for invalid file type
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    
    # Check response format
    error_data = response.json()
    assert "detail" in error_data

def test_ocr_processing_error():
    """Test error handling during OCR processing."""
    # Mock the PaddleOCR to raise an exception
    with patch('app.services.paddle_ocr.PaddleOCR') as mock_paddle_ocr:
        # Mock the OCR instance and its methods
        mock_ocr_instance = MagicMock()
        mock_ocr_instance.ocr.side_effect = Exception("OCR processing failed")
        mock_paddle_ocr.return_value = mock_ocr_instance
        
        # Create a test file
        dummy_file = io.BytesIO(b"fake image data")
        
        # Make the request
        response = client.post(
            "/api/v1/ocr/file",
            files={"file": ("test.jpg", dummy_file, "image/jpeg")},
            data={"document_type": "KTP"}
        )
        
        # The API returns 400 for OCR processing errors
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        
        # Check error response format
        error_data = response.json()
        assert "detail" in error_data

def test_invalid_document_type():
    """Test request with invalid document type."""
    dummy_file = io.BytesIO(b"fake image data")
    response = client.post(
        "/api/v1/ocr/file",
        files={"file": ("test.jpg", dummy_file, "image/jpeg")},
        data={"document_type": "INVALID_TYPE"}
    )
    
    # FastAPI returns 422 for invalid enum values
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    # Check response format
    error_data = response.json()
    assert "detail" in error_data

def test_missing_required_fields():
    """Test request with missing required fields."""
    # Missing document_type
    dummy_file = io.BytesIO(b"fake image data")
    response = client.post(
        "/api/v1/ocr/file",
        files={"file": ("test.jpg", dummy_file, "image/jpeg")}
    )
    
    # FastAPI returns 422 for missing required fields
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    
    # Check response format
    error_data = response.json()
    assert "detail" in error_data
