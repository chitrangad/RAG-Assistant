"""Error handler middleware — catches unhandled exceptions."""

from fastapi import Request
from fastapi.exceptions import HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from src.logging_config import get_logger

logger = get_logger(__name__)


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    """Catches unhandled exceptions and returns a consistent JSON error.

    Does NOT catch FastAPI's HTTPException — those are part of normal
    control flow (validation errors, 404s, etc.) and FastAPI handles them.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        try:
            return await call_next(request)
        except HTTPException:
            raise  # Let FastAPI's built-in handlers process it
        except Exception as exc:
            request_id = getattr(request.state, "request_id", "unknown")
            logger.exception(
                "unhandled_error",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
            )
            return JSONResponse(
                status_code=500,
                content={
                    "error": "internal_server_error",
                    "message": "An unexpected error occurred.",
                    "request_id": request_id,
                },
            )
