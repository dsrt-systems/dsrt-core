"""
Observability Middleware (C1 §42).

Injects request_id, tracks latency, and binds context variables to all structured logs.
Uses pure ASGI middleware (no BaseHTTPMiddleware) to eliminate Starlette TaskGroup 
event loop context conflicts with asyncpg.
"""

from __future__ import annotations

import time

import structlog
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.events.bus import ctx_request_id
from core.storage.identifiers import IdPrefix, new_id


class ObservabilityMiddleware:
    """Pure ASGI Middleware binding request_id to context and recording request timing."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers_dict = dict(scope.get("headers", []))
        request_id_bytes = headers_dict.get(b"x-request-id")
        request_id = (
            request_id_bytes.decode("latin1")
            if request_id_bytes
            else new_id(IdPrefix.REQUEST)
        )

        ctx_request_id.set(request_id)

        client = scope.get("client")
        client_ip = client[0] if client else None

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            client_ip=client_ip,
            method=scope.get("method"),
            path=scope.get("path"),
        )

        start_time = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                process_time = time.perf_counter() - start_time
                structlog.contextvars.bind_contextvars(
                    process_time_ms=round(process_time * 1000, 2)
                )
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Process-Time"] = str(process_time)
            await send(message)

        await self.app(scope, receive, send_wrapper)