import time
from fastapi import Request, Response
from fastapi.routing import APIRoute
from typing import Callable, Awaitable, Dict, Any
import logging

# Configure logging
logger = logging.getLogger(__name__)

class TimingMiddleware:
    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger("timing")
        self.logger.setLevel(logging.INFO)
        
        # Create console handler with a higher log level
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        
        # Create formatter and add it to the handlers
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        
        # Add the handler to the logger
        if not self.logger.handlers:  # Avoid adding multiple handlers
            self.logger.addHandler(ch)

    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Get the request start time
        start_time = time.time()
        
        # Create a custom send function to capture the response status
        async def send_wrapper(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                # Calculate processing time when we get the response start
                process_time = (time.time() - start_time) * 1000  # Convert to milliseconds
                
                # Get request details
                method = scope.get("method", "UNKNOWN")
                path = scope.get("path", "")
                status_code = message.get("status", 0)
                
                # Log the request details and processing time
                self.logger.info(
                    "Request processed | Method: %s | Path: %s | Status: %d | Duration: %.2fms",
                    method,
                    path,
                    status_code,
                    process_time
                )
                
                # Add Server-Timing header if not already present
                if "headers" not in message:
                    message["headers"] = []
                
                # Convert headers to lowercase for case-insensitive comparison
                header_names = [h[0].lower() for h in message["headers"]]
                
                # Add Server-Timing header if not already present
                if b"server-timing" not in header_names:
                    message["headers"].append((b"server-timing", f"total;dur={process_time:.2f}".encode()))
            
            await send(message)
        
        # Process the request with our custom send function
        await self.app(scope, receive, send_wrapper)

# Create a function to add the middleware to the FastAPI app
def add_timing_middleware(app):
    app.add_middleware(TimingMiddleware)
    return app
