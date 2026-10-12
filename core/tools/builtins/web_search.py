"""
web.search — Web Search Tool (C3 §7, §9).

Performs web searches using a configurable search backend.
For C3.7, uses DuckDuckGo's HTML interface (no API key required)
as the default backend, with support for custom search providers
via environment configuration.
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone
from typing import Any

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


logger = get_logger("dsrt.tools.web_search")

_DEFAULT_TIMEOUT = 20
_DEFAULT_MAX_RESULTS = 10
_MAX_QUERY_LENGTH = 500
_SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"

# Regex to extract result blocks from DuckDuckGo HTML
_RESULT_PATTERN = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    """Strip HTML tags and normalize whitespace."""
    cleaned = _HTML_TAG_PATTERN.sub("", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class WebSearchTool(BuiltinToolBase):
    """Universal web search tool."""

    identity = ToolIdentity(
        slug="web.search",
        name="Web Search",
        version="1.0.0",
        contract_version="1.0",
        publisher="dsrt",
        category="web",
    )

    manifest = ToolManifest(
        identity=identity,
        description=(
            "Search the web for current information. Returns a ranked list of "
            "results with URLs, titles, and snippets. Uses DuckDuckGo as the "
            "default search provider (no API key required)."
        ),
        capabilities=[
            ToolCapabilityDeclaration(slug="web.search", description="Web search"),
            ToolCapabilityDeclaration(slug="information.retrieval"),
        ],
        permissions=ToolPermissionDeclaration(
            network=ToolNetworkPermission(required=True, outbound=True),
        ),
        risk_level=ToolRiskLevel.LOW,
        side_effect=SideEffectClass.READ,
        limits=ToolLimits(
            timeout_seconds=_DEFAULT_TIMEOUT,
            max_output_bytes=2 * 1024 * 1024,  # 2 MB
        ),
        retry=ToolRetryPolicy(allowed=True, max_attempts=3, idempotent=True),
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "default": 10},
                "timeout_seconds": {"type": "integer"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "result_count": {"type": "integer"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "title": {"type": "string"},
                            "snippet": {"type": "string"},
                        },
                    },
                },
            },
        },
    )

    async def execute(
        self, request: ToolExecutionRequest,
    ) -> ToolExecutionResult:
        start_time = time.perf_counter()
        args = request.arguments or {}

        query = args.get("query")
        max_results = int(args.get("max_results") or _DEFAULT_MAX_RESULTS)
        timeout = int(args.get("timeout_seconds") or _DEFAULT_TIMEOUT)

        if not query or not isinstance(query, str):
            return self._error_result(
                request, start_time,
                "TOOL_INVALID_ARGUMENT",
                "Missing or invalid 'query' argument.",
            )

        if len(query) > _MAX_QUERY_LENGTH:
            return self._error_result(
                request, start_time,
                "TOOL_INVALID_ARGUMENT",
                f"Query exceeds max length ({_MAX_QUERY_LENGTH}).",
            )

        max_results = max(1, min(max_results, 50))

        if self._is_cancelled(request.request_id):
            return self._error_result(
                request, start_time,
                "TOOL_CANCELLED",
                "Request cancelled before execution.",
            )

        # --- Perform search ---
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; DSRT-Agent/1.0)",
                },
            ) as client:
                response = await client.post(
                    _SEARCH_ENDPOINT,
                    data={"q": query, "kl": "us-en"},
                )
                response.raise_for_status()
                html = response.text

        except httpx.TimeoutException as e:
            return self._error_result(
                request, start_time,
                "TOOL_TIMEOUT",
                f"Search timed out: {e}",
                retryable=True,
            )
        except httpx.NetworkError as e:
            return self._error_result(
                request, start_time,
                "TOOL_NETWORK_FAILURE",
                f"Network error during search: {e}",
                retryable=True,
            )
        except httpx.HTTPStatusError as e:
            return self._error_result(
                request, start_time,
                "TOOL_RUNTIME_FAILURE",
                f"Search endpoint returned {e.response.status_code}",
                retryable=False,
            )
        except Exception as e:
            return self._error_result(
                request, start_time,
                "TOOL_RUNTIME_FAILURE",
                f"Search failed: {e}",
                retryable=False,
            )

        # --- Parse results ---
        results: list[dict[str, str]] = []
        for match in _RESULT_PATTERN.finditer(html):
            if len(results) >= max_results:
                break
            raw_url, raw_title, raw_snippet = match.groups()
            url = raw_url.strip()
            title = _strip_html(raw_title)
            snippet = _strip_html(raw_snippet)
            if url and title:
                results.append({
                    "url": url,
                    "title": title,
                    "snippet": snippet,
                })

        duration_ms = int((time.perf_counter() - start_time) * 1000)
        now = datetime.now(timezone.utc)

        output = {
            "query": query,
            "result_count": len(results),
            "results": results,
        }

        observation = ToolObservation(
            observation_id=new_id(IdPrefix.TOOL_OBSERVATION),
            observation_type=ObservationType.SEARCH_RESULTS,
            content=output,
            summary=f"Search '{query}' returned {len(results)} results",
            source=self.identity.slug,
            timestamp=now,
            size_bytes=len(str(output).encode("utf-8")),
            provenance={
                "tool_slug": self.identity.slug,
                "tool_execution_id": request.request_id,
                "execution_id": request.execution_id,
                "search_provider": "duckduckgo",
                "query": query,
            },
        )

        logger.info(
            "web_search_completed",
            query=query,
            result_count=len(results),
            duration_ms=duration_ms,
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