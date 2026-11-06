"""Request-ID and timing middleware, JSON request logging, and the error envelope handlers.

The middleware is plain ASGI (not BaseHTTPMiddleware) so streaming responses and
client-disconnect detection keep working.
"""

import logging
import re
import time
import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ai_service.core.exceptions import AppError
from ai_service.schemas.common import ErrorDetail, ErrorResponse

logger = logging.getLogger("ai_service.request")

REQUEST_ID_HEADER = "X-Request-ID"
# Only accept a client-supplied id that is short and harmless (it ends up in logs and headers).
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")

_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "VALIDATION_ERROR",
    429: "TOO_MANY_REQUESTS",
}


class RequestContextMiddleware:
    """Assign a request id, time the request, and write one JSON log line per request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    # scope = req, receive = req.on('data'), send = req.write()/req.end(), self.app = next()
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = MutableHeaders(scope=scope).get(REQUEST_ID_HEADER, "")
        request_id = incoming if _SAFE_REQUEST_ID.fullmatch(incoming) else str(uuid.uuid4())
        state: dict[str, Any] = scope.setdefault("state", {})
        state["request_id"] = request_id

        start = time.perf_counter()
        status_code = 500

        async def send_with_headers(message: Message) -> None:
            # Modify the status_code variable from the outer function so our logger can use it later!
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
                headers["X-Process-Time"] = f"{(time.perf_counter() - start) * 1000:.2f}ms"
            await send(message)

        try:
            # in Express term, its next()
            await self.app(scope, receive, send_with_headers)
        finally:
            # After route has returned (whether successful or not), we calculate the duration.
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            logger.info(
                "%s %s -> %s",
                scope["method"],
                scope["path"],
                status_code,
                extra={
                    "request_id": request_id,
                    "tenant_id": state.get("tenant_id"),
                    "user_id": state.get("user_id"),
                    "method": scope["method"],
                    "path": scope["path"],
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )


def request_id_of(request: Request) -> str | None:
    state: dict[str, Any] = request.scope.get("state", {})
    return state.get("request_id")


def error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    details: Any = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    request_id = request_id_of(request)
    body = ErrorResponse(
        error=ErrorDetail(code=code, message=message, request_id=request_id, details=details)
    )
    response_headers = dict(headers or {})
    if request_id:
        response_headers[REQUEST_ID_HEADER] = request_id
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(exclude_none=True),
        headers=response_headers,
    )


async def handle_app_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return error_response(
        request, exc.status_code, exc.code, exc.message, details=exc.details, headers=exc.headers
    )


async def handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
    headers = dict(exc.headers) if exc.headers else None
    return error_response(request, exc.status_code, code, str(exc.detail), headers=headers)


async def handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {
            "location": [str(part) for part in error["loc"]],
            "message": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()
    ]
    return error_response(
        request, 422, "VALIDATION_ERROR", "The request is not valid.", details=details
    )


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(
        "Unhandled error",
        extra={"request_id": request_id_of(request), "path": request.url.path},
    )
    return error_response(request, 500, "INTERNAL_ERROR", "Internal server error.")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, handle_app_error)
    app.add_exception_handler(StarletteHTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
