"""
FastAPI exception handlers that convert every error into the normalized envelope.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from core.api.errors.exceptions import DSRTError, ValidationError
from core.observability.logging import get_logger
from schemas.domain.enums import ErrorCode


logger = get_logger("dsrt.api.errors")


def register_error_handlers(app: FastAPI) -> None:
    """Register DSRT's normalized error responses."""

    @app.exception_handler(DSRTError)
    async def _handle_dsrt_error(request: Request, exc: DSRTError) -> JSONResponse:
        logger.warning(
            "dsrt_error",
            code=exc.error_code.value,
            http_status=exc.http_status,
            path=request.url.path,
        )
        return JSONResponse(status_code=exc.http_status, content=exc.to_response())

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError,
    ) -> JSONResponse:
        # Pydantic validation failures at the request boundary.
        errors: list[dict] = []
        for e in exc.errors():
            errors.append(
                {
                    "location": ".".join(str(p) for p in e.get("loc", [])),
                    "message": e.get("msg"),
                    "type": e.get("type"),
                }
            )
        dsrt_exc = ValidationError(
            "Request validation failed.",
            metadata={"errors": errors},
        )
        logger.info("request_validation_failed", path=request.url.path)
        return JSONResponse(
            status_code=dsrt_exc.http_status, content=dsrt_exc.to_response(),
        )

    @app.exception_handler(Exception)
    async def _handle_unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internal traces to the client.
        logger.exception(
            "unhandled_exception",
            exc_type=type(exc).__name__,
            path=request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": ErrorCode.INTERNAL_ERROR.value,
                    "message": "An internal error occurred.",
                    "metadata": {},
                }
            },
        )
