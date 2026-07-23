"""
Version Header Middleware

This middleware adds an X-API-Version header to all responses.
"""
from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

class VersionHeaderMiddleware:
    """Middleware to add X-API-Version header to all responses."""
    
    def __init__(self, app, version: str = "v1"):
        self.app = app
        self.version = version
    
    async def __call__(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers["X-API-Version"] = self.version
        return response
