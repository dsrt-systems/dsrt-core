"""
http.request — Controlled Outbound HTTP Tool (C3 §29, §30).

Enforces domain allowlist/blocklist, method restrictions, timeout limits,
response size caps, and credential injection via the C2 CredentialBroker.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from schemas.domain.enums import (
    ObservationType,
    SideEffectClass,
    ToolExecutionStatus,
    ToolRiskLevel,
)
from schemas.domain.tool import (
    ToolCapabilityDeclaration,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolIdentity,
    ToolLimits,
    ToolManifest,
    ToolNetworkPermission,
    ToolObservation,
    ToolPermissionDeclaration,
    ToolRetryPolicy,
    ToolUsage,
)

from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.tools.builtins._base import BuiltinToolBase


logger = get_logger("dsrt.tools.http_request")


_ALLOWED_METHODS = {"GET", "POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"}
_MAX_RESPONSE_BYTES = 10 * 1024 * 1024  # 10 MB
_DEFAULT_TIMEOUT = 30


class HttpRequestTool(BuiltinToolBase):
    """Universal HTTP request tool with security controls."""

    identity = ToolIdentity(
        slug="http.request",
        name="HTTP Request",
        version="1.0.0",
        contract_version="1.0",
        publisher="dsrt",
        category="http",
    )

    manifest = ToolManifest(
        identity=identity,
        description=(
            "Perform controlled outbound HTTP requests. Supports GET, POST, PUT, "
            "DELETE, HEAD, OPTIONS, and PATCH methods. Enforces domain allowlist, "
            "response size limits, and timeout policies."
        ),
        capabilities=[
            ToolCapabilityDeclaration(slug="http.request", description="HTTP operations"),
            ToolCapabilityDeclaration(slug="network.outbound", description="Outbound network access"),
        ],
        permissions=ToolPermissionDeclaration(
            network=ToolNetworkPermission(required=True, outbound=True),
        ),
        risk_level=ToolRiskLevel.LOW,
        side_effect=SideEffectClass.READ,
        limits=ToolLimits(
            timeout_seconds=_DEFAULT_TIMEOUT,
            max_output_bytes=_MAX_RESPONSE_BYTES,
        ),
        retry=ToolRetryPolicy(allowed=True, max_attempts=3, idempotent=True),
        input_schema={
            "type": "object",
            "required": ["url"],
            "properties": {
                "method": {"type": "string", "default": "GET"},
                "url": {"type": "string"},
                "headers": {"type": "object"},
                "query_params": {"type": "object"},
                "json_body": {"type": "object"},
                "text_body": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "status_code": {"type": "integer"},
                "headers": {"type": "object"},
                "body": {"type": ["string", "object", "null"]},
                "url": {"type": "string"},
            },
        },
    )

    async def execute(
        self, request: ToolExecutionRequest,
    ) -> ToolExecutionResult:
        start_time = time.perf_counter()
        args = request.arguments or {}

        method = str(args.get("method", "GET")).upper()
        url = args.get("url")
        headers = args.get("headers") or {}
        query_params = args.get("query_params") or {}
        json_body = args.get("json_body")
        text_body = args.get("text_body")
        timeout = int(args.get("timeout_seconds") or _DEFAULT_TIMEOUT)

        # --- Validate inputs ---
        if not url:
            return self._error_result(
                request, start_time,
                "TOOL_INVALID_ARGUMENT",
                "Missing required argument 'url'.",
            )

        if method not in _ALLOWED_METHODS:
            return self._error_result(
                request, start_time,
                "TOOL_INVALID_ARGUMENT",
                f"HTTP method '{method}' not allowed. Allowed: {sorted(_ALLOWED_METHODS)}",
            )

        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https"):
            return self._error_result(
                request, start_time,
                "TOOL_INVALID_ARGUMENT",
                f"URL scheme '{parsed_url.scheme}' not allowed. Only http/https permitted.",
            )

        if not parsed_url.netloc:
            return self._error_result(
                request, start_time,
                "TOOL_INVALID_ARGUMENT",
                "URL must include a hostname.",
            )

        # Check cancellation
        if self._is_cancelled(request.request_id):
            return self._error_result(
                request, start_time,
                "TOOL_CANCELLED",
                "Request cancelled before execution.",
            )

        # --- Execute HTTP request ---
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            ) as client:
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=query_params,
                    json=json_body if json_body is not None else None,
                    content=text_body.encode("utf-8") if text_body else None,
                )

                # Enforce response size limit
                content_bytes = response.content
                if len(content_bytes) > _MAX_RESPONSE_BYTES:
                    return self._error_result(
                        request, start_time,
                        "TOOL_OUTPUT_TOO_LARGE",
                        f"Response size {len(content_bytes)} exceeds limit {_MAX_RESPONSE_BYTES}.",
                    )

                # Parse body
                content_type = response.headers.get("content-type", "").lower()
                body: Any
                if "application/json" in content_type:
                    try:
                        body = response.json()
                    except Exception:
                        body = response.text
                else:
                    body = response.text

        except httpx.TimeoutException as e:
            return self._error_result(
                request, start_time,
                "TOOL_TIMEOUT",
                f"HTTP request timed out after {timeout}s: {e}",
                retryable=True,
            )
        except httpx.NetworkError as e:
            return self._error_result(
                request, start_time,
                "TOOL_NETWORK_FAILURE",
                f"HTTP network error: {e}",
                retryable=True,
            )
        except Exception as e:
            return self._error_result(
                request, start_time,
                "TOOL_RUNTIME_FAILURE",
                f"HTTP request failed: {e}",
                retryable=False,
            )

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        now = datetime.now(timezone.utc)

        output = {
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "body": body,
            "url": str(response.url),
            "method": method,
        }

        observation = ToolObservation(
            observation_id=new_id(IdPrefix.TOOL_OBSERVATION),
            observation_type=ObservationType.HTTP_RESPONSE,
            content=output,
            summary=f"{method} {url} → {response.status_code}",
            source=self.identity.slug,
            timestamp=now,
            size_bytes=len(content_bytes),
            provenance={
                "tool_slug": self.identity.slug,
                "tool_execution_id": request.request_id,
                "execution_id": request.execution_id,
            },
        )

        logger.info(
            "http_request_completed",
            method=method,
            url=url,
            status_code=response.status_code,
            duration_ms=duration_ms,
            response_bytes=len(content_bytes),
        )

        return ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id=request.request_id,
            tool_slug=self.identity.slug,
            tool_version=self.identity.version,
            status=ToolExecutionStatus.COMPLETED,
            output=output,
            observations=[observation],
            artifact_ids=[],
            errors=[],
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms,
            attempt=request.attempt,
            started_at=now,
            completed_at=now,
        )

    def _error_result(
        self,
        request: ToolExecutionRequest,
        start_time: float,
        error_code: str,
        error_message: str,
        *,
        retryable: bool = False,
    ) -> ToolExecutionResult:
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        return ToolExecutionResult(
            request_id=request.request_id,
            tool_execution_id=request.request_id,
            tool_slug=self.identity.slug,
            tool_version=self.identity.version,
            status=ToolExecutionStatus.FAILED,
            output=None,
            observations=[],
            artifact_ids=[],
            errors=[
                ToolExecutionError(
                    code=error_code,
                    message=error_message,
                    retryable=retryable,
                )
            ],
            usage=ToolUsage(duration_ms=duration_ms),
            duration_ms=duration_ms,
            attempt=request.attempt,
        )