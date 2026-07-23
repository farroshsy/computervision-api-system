"""Authentication middleware for API key validation."""
from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import settings
from app.schemas.error import create_error_response, ErrorCode

# API key header configuration
API_KEY_HEADER = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_HEADER, auto_error=False)


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware to validate API keys for all requests."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # Skip auth for health check, docs, and metrics endpoints
        excluded_paths = [
            "/",  # Root endpoint
            "/health",
            "/docs",
            "/openapi.json",
            "/redoc",
            "/metrics"  # Allow Prometheus to scrape metrics without authentication
        ]
        
        if any(request.url.path.startswith(path) for path in excluded_paths):
            return await call_next(request)

        # Get API key from header
        api_key = request.headers.get(API_KEY_HEADER.lower())
        
        # Validate API key
        if not settings.REQUIRE_API_KEY:
            return await call_next(request)
            
        if not api_key or api_key != settings.API_KEY:
            # Create error response with the expected schema
            error_response = {
                "error": {
                    "code": "unauthorized",
                    "message": "Invalid or missing API key",
                    "status_code": status.HTTP_401_UNAUTHORIZED
                }
            }
            
            # Get or generate request ID
            if not hasattr(request.state, 'request_id'):
                import uuid
                request.state.request_id = str(uuid.uuid4())
                
            # Create response with request ID in headers
            response = JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content=error_response
            )
            response.headers["X-Request-ID"] = request.state.request_id
            return response

        # Continue processing the request
        return await call_next(request)
