"""
web.retrieve — Web Page Content Retrieval Tool (C3 §29).

Fetches HTML/text content from a URL and returns it as a PAGE_CONTENT
observation. Uses HTTP under the hood but exposes a cleaner interface
for agents that just need page content.
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


logger = get_logger("dsrt.tools.web_retrieve")

_MAX_CONTENT_BYTES = 5 * 1024 * 1024  # 5 MB
_DEFAULT_TIMEOUT = 30
_DEFAULT_USER_AGENT = "DSRT-Research-Agent/1.0"


class WebRetrieveTool(BuiltinToolBase):
    """Fetches web page content as a structured observation."""

    identity = ToolIdentity(
        slug="web.retrieve",
        name="Web Retrieve",
        version="1.0.0",
        contract_version="1.0",
        publisher="dsrt",
        category="web",
    )

    manifest = ToolManifest(
        identity=identity,
        description=(
            "Fetch content from a web URL. Returns the raw HTML/text body "
            "as a PAGE_CONTENT observation with content-type metadata."
        ),
        capabilities=[
            ToolCapabilityDeclaration(slug="web.retrieve", description="Fetch web pages"),
            ToolCapabilityDeclaration(slug="information.retrieval"),
        ],
        permissions=ToolPermissionDeclaration(
            network=ToolNetworkPermission(required=True, outbound=True),
        ),
        risk_level=ToolRiskLevel.LOW,
        side_effect=SideEffectClass.READ,
        limits=ToolLimits(
            timeout_seconds=_DEFAULT_TIMEOUT,
            max_output_bytes=_MAX_CONTENT_BYTES,
        ),
        retry=ToolRetryPolicy(allowed=True, max_attempts=3, idempotent=True),
        input_schema={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string"},
                "timeout_seconds": {"type": "integer"},
                "user_agent": {"type": "string"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "content_type": {"type": "string"},
                "content": {"type": "string"},
                "status_code": {"type": "integer"},
                "size_bytes": {"type": "integer"},
            },
        },
    )

    async def execute(
        self, request: ToolExecutionRequest,
    ) -> ToolExecutionResult:
        start_time = time.perf_counter()
        args = request.arguments or {}

        url = args.get("url")
        timeout = int(args.get("timeout_seconds") or _DEFAULT_TIMEOUT)
        user_agent = args.get("user_agent") or _DEFAULT_USER_AGENT

        if not url:
            return self._error_result(
                request, start_time,
                "TOOL_INVALID_ARGUMENT",
                "Missing required argument 'url'.",
            )

        parsed_url = urlparse(url)
        if parsed_url.scheme not in ("http", "https"):
            return self._error_result(
                request, start_time,
                "TOOL_INVALID_ARGUMENT",
                f"URL scheme '{parsed_url.scheme}' not allowed.",
            )

        if self._is_cancelled(request.request_id):
            return self._error_result(
                request, start_time,
                "TOOL_CANCELLED",
                "Request cancelled before execution.",
            )

        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={"User-Agent": user_agent},
            ) as client:
                response = await client.get(url)

                content_bytes = response.content
                if len(content_bytes) > _MAX_CONTENT_BYTES:
                    return self._error_result(
                        request, start_time,
                        "TOOL_OUTPUT_TOO_LARGE",
                        f"Content size {len(content_bytes)} exceeds limit {_MAX_CONTENT_BYTES}.",
                    )

                content_type = response.headers.get("content-type", "text/html").lower()
                content_text = response.text

        except httpx.TimeoutException as e:
            return self._error_result(
                request, start_time,
                "TOOL_TIMEOUT",
                f"Web retrieve timed out: {e}",
                retryable=True,
            )
        except httpx.NetworkError as e:
            return self._error_result(
                request, start_time,
                "TOOL_NETWORK_FAILURE",
                f"Network error: {e}",
                retryable=True,
            )
        except Exception as e:
            return self._error_result(
                request, start_time,
                "TOOL_RUNTIME_FAILURE",
                f"Web retrieve failed: {e}",
                retryable=False,
            )

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        now = datetime.now(timezone.utc)

        output = {
            "url": str(response.url),
            "content_type": content_type,
            "content": content_text,
            "status_code": response.status_code,
            "size_bytes": len(content_bytes),
        }

        observation = ToolObservation(
            observation_id=new_id(IdPrefix.TOOL_OBSERVATION),
            observation_type=ObservationType.PAGE_CONTENT,
            content={
                "url": str(response.url),
                "content_type": content_type,
                "content": content_text,
            },
            summary=f"Retrieved {url} ({len(content_bytes)} bytes, {content_type})",
            source=self.identity.slug,
            timestamp=now,
            size_bytes=len(content_bytes),
            provenance={
                "tool_slug": self.identity.slug,
                "tool_execution_id": request.request_id,
                "execution_id": request.execution_id,
                "source_url": str(response.url),
            },
        )

        logger.info(
            "web_retrieve_completed",
            url=url,
            status_code=response.status_code,
            duration_ms=duration_ms,
            content_bytes=len(content_bytes),
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