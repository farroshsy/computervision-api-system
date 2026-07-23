"""Middleware for generating and attaching request IDs to all requests."""
import uuid
from typing import Optional
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Middleware that generates a unique request ID for each incoming request."""
    
    def __init__(self, app: ASGIApp, header_name: str = "X-Request-ID"):
        super().__init__(app)
        self.header_name = header_name
    
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        # Get request ID from header or generate a new one
        request_id = request.headers.get(self.header_name.lower()) or str(uuid.uuid4())
        
        # Store request ID in request state
        request.state.request_id = request_id
        
        # Call the next middleware/route handler
        response = await call_next(request)
        
        # Add request ID to response headers
        response.headers[self.header_name] = request_id
        
        return response
