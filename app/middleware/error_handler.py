from fastapi import Request, status
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging
from typing import Any, Callable, Dict, Optional, Union
import json
import traceback

logger = logging.getLogger(__name__)

class APIError(Exception):
    def __init__(
        self,
        status_code: int = 500,
        error_code: str = "internal_server_error",
        message: str = "An unexpected error occurred",
        details: Optional[Any] = None
    ):
        self.status_code = status_code
        self.error_code = error_code
        self.message = message
        self.details = details
        super().__init__(self.message)

class ErrorHandlerMiddleware:
    def __init__(self, app):
        self.app = app
        self.logger = logging.getLogger("error_handler")
        
    async def __call__(self, scope: Dict[str, Any], receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        
        async def send_wrapper(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start" and message["status"] >= 400:
                self.logger.error(
                    f"Error response: {message['status']} for {request.method} {request.url.path}"
                )
            await send(message)
        
        try:
            await self.app(scope, receive, send_wrapper)
        except RequestValidationError as exc:
            await self.handle_validation_error(exc, scope, send)
        except APIError as exc:
            await self.handle_api_error(exc, scope, send)
        except Exception as exc:
            await self.handle_unexpected_error(exc, scope, send)
    
    async def handle_validation_error(
        self, exc: RequestValidationError, scope: Dict[str, Any], send: Callable
    ) -> None:
        self.logger.warning(f"Validation error: {exc}")
        
        error_response = {
            "error": {
                "code": "validation_error",
                "message": "Invalid request data",
                "details": [
                    {
                        "loc": ".".join(str(loc) for loc in err["loc"]),
                        "msg": err["msg"],
                        "type": err["type"],
                    }
                    for err in exc.errors()
                ],
            }
        }
        
        await self.send_error_response(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            error_response=error_response,
            send=send,
        )
    
    async def handle_api_error(
        self, exc: 'APIError', scope: Dict[str, Any], send: Callable
    ) -> None:
        self.logger.error(f"API error: {exc}")
        
        error_response = {
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
            }
        }
        
        await self.send_error_response(
            status_code=exc.status_code,
            error_response=error_response,
            send=send,
        )
    
    async def handle_unexpected_error(
        self, exc: Exception, scope: Dict[str, Any], send: Callable
    ) -> None:
        error_id = id(exc)
        self.logger.error(
            f"Unexpected error (ID: {error_id}): {exc}\n"
            f"Traceback: {''.join(traceback.format_exception(type(exc), exc, exc.__traceback__))}"
        )
        
        error_response = {
            "error": {
                "code": "internal_server_error",
                "message": "An unexpected error occurred",
                "reference": str(error_id),
            }
        }
        
        await self.send_error_response(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            error_response=error_response,
            send=send,
        )
    
    async def send_error_response(
        self, status_code: int, error_response: Dict[str, Any], send: Callable
    ) -> None:
        response = {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
            ],
        }
        await send(response)
        
        body = json.dumps(error_response).encode("utf-8")
        await send({
            "type": "http.response.body",
            "body": body,
            "more_body": False,
        })
