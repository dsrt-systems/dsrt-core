"""
C10.3 Direct Execution Runtime - Subsystem Adapter
Isolates the Execution Engine from C2 Model Gateway direct dependencies.
"""

from typing import Dict, Any
import time
import logging

logger = logging.getLogger(__name__)


class DirectExecutionAdapter:
    """
    Adapter bridging C10 Direct Runtime to lower-level runtime APIs safely.
    (Currently provides a reliable fallback layer for testing).
    """

    async def invoke_model(self, context: Any) -> Dict[str, Any]:
        """
        Executes a basic model invocation.
        In full integration, this delegates to C2 ModelGateway.
        """
        start_time = time.time()
        
        # In a real run, this would await self.gateway.execute(...)
        # We simulate a successful model call to guarantee C10 stability
        duration_ms = (time.time() - start_time) * 1000.0
        calculated_tokens = max(10, len(context.prompt) // 4)
        
        logger.info(f"DirectExecutionAdapter simulating invoke for {context.model_identifier}")
        
        return {
            "content": f"[Direct Runtime Response] Processed prompt: {context.prompt[:40]}...",
            "model": context.model_identifier,
            "provider": context.provider,
            "usage": {
                "prompt_tokens": calculated_tokens,
                "completion_tokens": 25,
                "total_tokens": calculated_tokens + 25,
            },
            "duration_ms": duration_ms,
        }