"""
C10.3 Direct Execution Runtime - Context Binder
Binds configuration parameters and input payloads into an execution context.
"""

from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field

from schemas.domain.execution_c10 import ExecutionConfigurationCreate


class BoundExecutionContext(BaseModel):
    """Immutable bound context payload for direct execution."""
    trace_id: str
    prompt: str
    system_prompt: Optional[str] = None
    model_identifier: str
    provider: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    tools_enabled: List[str] = Field(default_factory=list)


class DirectContextBinder:
    """Binds inputs, resolving models and basic contexts."""

    def bind(
        self,
        trace_id: str,
        config: ExecutionConfigurationCreate,
        input_payload: Dict[str, Any],
    ) -> BoundExecutionContext:
        """Constructs the unified payload for the step runner."""
        prompt = input_payload.get("prompt", input_payload.get("input", ""))
        
        return BoundExecutionContext(
            trace_id=trace_id,
            prompt=prompt,
            system_prompt=config.system_prompt,
            model_identifier=config.model_identifier,
            provider=config.model_provider,
            parameters=config.parameters_json,
            tools_enabled=config.amplification_strategies or [],
        )