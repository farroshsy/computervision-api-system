"""Pytest configuration and fixtures."""
import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings

# Set up test environment variables
os.environ["REQUIRE_API_KEY"] = "false"  # Disable auth for tests
os.environ["RATE_LIMIT_ENABLED"] = "false"  # Disable rate limiting for tests

@pytest.fixture(scope="module")
def test_client():
    """Create a test client with disabled authentication."""
    # Create a test client with the FastAPI app
    with TestClient(app) as client:
        yield client

@pytest.fixture(scope="module")
def auth_client():
    """Create a test client with valid authentication."""
    # Create a test client with the FastAPI app and valid auth headers
    with TestClient(app) as client:
        client.headers.update({"X-API-Key": settings.API_KEY})
        yield client
