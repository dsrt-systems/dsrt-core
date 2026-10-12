"""
Tool Retry Executor (C3 §47).

Executes tool calls with retry logic respecting the ToolRetryPolicy
declared in the tool manifest.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from schemas.domain.tool import ToolExecutionResult, ToolRetryPolicy

from core.observability.logging import get_logger
from core.tools.errors import ToolRuntimeError


logger = get_logger("dsrt.tools.retry")


async def execute_with_retry(
    execute_fn: Callable[[], Coroutine[Any, Any, ToolExecutionResult]],
    retry_policy: ToolRetryPolicy,
    *,
    cancel_event: asyncio.Event | None = None,
) -> ToolExecutionResult:
    """Execute a tool call with retry logic.

    Args:
        execute_fn: Async callable that performs the tool execution.
        retry_policy: The tool's declared retry policy.
        cancel_event: Optional cancellation event to check between retries.

    Returns:
        The final ToolExecutionResult (success or last failure).
    """
    if not retry_policy.allowed or retry_policy.max_attempts <= 1:
        return await execute_fn()

    last_result: ToolExecutionResult | None = None
    backoff = retry_policy.backoff_seconds

    for attempt in range(1, retry_policy.max_attempts + 1):
        # Check cancellation before each attempt
        if cancel_event and cancel_event.is_set():
            logger.info("tool_retry_cancelled", attempt=attempt)
            if last_result:
                return last_result
            raise ToolRuntimeError("Tool execution cancelled during retry.")

        try:
            result = await execute_fn()

            # If the result indicates failure and is retryable, continue
            if result.status.value == "FAILED" and attempt < retry_policy.max_attempts:
                # Check if any error is retryable
                has_retryable = any(e.retryable for e in result.errors)
                if has_retryable:
                    logger.warning(
                        "tool_retry_attempt_failed",
                        attempt=attempt,
                        max_attempts=retry_policy.max_attempts,
                        backoff_seconds=backoff,
                    )
                    last_result = result
                    await asyncio.sleep(backoff)
                    backoff = min(
                        backoff * retry_policy.backoff_multiplier,
                        retry_policy.max_backoff_seconds,
                    )
                    continue
                else:
                    # Non-retryable failure — stop immediately
                    return result

            return result

        except ToolRuntimeError as e:
            if attempt < retry_policy.max_attempts:
                logger.warning(
                    "tool_retry_exception",
                    attempt=attempt,
                    error=str(e),
                    backoff_seconds=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(
                    backoff * retry_policy.backoff_multiplier,
                    retry_policy.max_backoff_seconds,
                )
                continue
            raise

    # Should not reach here, but return last result if we do
    if last_result:
        return last_result
    raise ToolRuntimeError("Tool retry exhausted with no result.")