"""Rate limiting middleware using slowapi."""
from typing import Callable, Optional, Dict, Any, List, TypeVar, cast
from functools import wraps

from fastapi import Request, HTTPException, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.config import settings

# Type variable for generic function typing
F = TypeVar('F', bound=Callable[..., Any])

# Initialize the rate limiter with a simple in-memory storage
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[f"{settings.GLOBAL_RATE_LIMIT}/minute"],
)

def rate_limit(
    key_func: Optional[Callable[[Request], str]] = None,
    default_limits: Optional[List[str]] = None,
    error_message: Optional[str] = None,
    exempt_when: Optional[Callable[[Request], bool]] = None,
    error_status_code: int = status.HTTP_429_TOO_MANY_REQUESTS,
    error_headers: Optional[Dict[str, str]] = None,
) -> Callable[[F], F]:
    """Decorator to apply rate limiting to a route.
    
    Args:
        key_func: Function to generate rate limit key. Defaults to remote address.
        default_limits: List of rate limits (e.g., ["5 per minute", "100 per day"]).
        error_message: Custom error message when rate limit is exceeded.
        exempt_when: Function that returns True to exempt the request from rate limiting.
        error_status_code: HTTP status code for rate limit exceeded responses.
        error_headers: Additional headers to include in rate limit exceeded responses.
        
    Returns:
        Decorated route function with rate limiting applied.
    """
    def decorator(func: F) -> F:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Get the request object from the arguments
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break
                
            if not request:
                for value in kwargs.values():
                    if isinstance(value, Request):
                        request = value
                        break
            
            if not request:
                raise RuntimeError("Could not find request object in function arguments")
            
            # Skip rate limiting for exempted requests
            if exempt_when and exempt_when(request):
                return await func(*args, **kwargs)
            
            # Skip rate limiting if disabled in settings
            if not settings.RATE_LIMIT_ENABLED:
                return await func(*args, **kwargs)
            
            # Apply rate limiting
            try:
                # Check if this is an API key that bypasses rate limiting
                api_key = request.headers.get("X-API-Key")
                if api_key in (settings.RATE_LIMIT_BYPASS_KEYS or []):
                    return await func(*args, **kwargs)
                
                # Use API key for rate limiting if available, otherwise use IP
                if api_key:
                    key = f"api_key:{api_key}"
                    # Apply higher rate limit for API keys
                    limiter.check(request, key, [f"{settings.API_KEY_RATE_LIMIT}/minute"])
                else:
                    # Apply global rate limit for IP-based requests
                    limiter.check(request)
                
                # Call the original function
                return await func(*args, **kwargs)
                
            except RateLimitExceeded as exc:
                # Handle rate limit exceeded
                error_msg = error_message or "Rate limit exceeded"
                
                # Include rate limit headers in the response
                headers = error_headers or {}
                headers.update({
                    "Retry-After": str(int(exc.retry_after)),
                })
                
                return JSONResponse(
                    status_code=error_status_code,
                    content={
                        "error": {
                            "code": "rate_limit_exceeded",
                            "message": error_msg,
                            "retry_after": exc.retry_after,
                        }
                    },
                    headers=headers,
                )
        
        # Store rate limit information on the wrapper function
        if default_limits:
            wrapper.__rate_limits__ = default_limits
        
        return cast(F, wrapper)
    
    return decorator

def setup_rate_limiter(app):
    """Set up rate limiting for the FastAPI application.
    
    Args:
        app: FastAPI application instance.
    """
    # Only add rate limiting middleware if enabled in settings
    if settings.RATE_LIMIT_ENABLED:
        # Add rate limiting middleware
        app.state.limiter = limiter
        
        # Add rate limit information to the OpenAPI schema
        @app.middleware("http")
        async def add_rate_limit_headers(request: Request, call_next):
            response = await call_next(request)
            
            # Add rate limit headers to all responses
            if hasattr(request.state, "rate_limit"):
                response.headers["X-RateLimit-Limit"] = str(request.state.rate_limit.limit)
                response.headers["X-RateLimit-Remaining"] = str(request.state.rate_limit.remaining)
                
                if hasattr(request.state.rate_limit, "reset_at"):
                    response.headers["X-RateLimit-Reset"] = str(request.state.rate_limit.reset_at)
            
            return response
    
    return app
