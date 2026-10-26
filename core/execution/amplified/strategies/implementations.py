"""
C10.4 Amplification Runtime - Strategies
Implements the 5 core amplification strategies mandated by D9.
"""

from typing import Dict, Any
from abc import ABC, abstractmethod

from schemas.domain.enums import AmplificationStrategy
from core.execution.amplified.adapter import AmplifiedSubsystemAdapter


class BaseStrategy(ABC):
    """Abstract contract for an Amplification Strategy."""
    strategy_type: AmplificationStrategy

    def __init__(self, adapter: AmplifiedSubsystemAdapter):
        self.adapter = adapter

    @abstractmethod
    async def execute(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        """Executes the strategy, modifying pipeline state and returning metrics."""
        pass


class ContextRetrievalStrategy(BaseStrategy):
    strategy_type = AmplificationStrategy.CONTEXT_RETRIEVAL

    async def execute(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        prompt = payload.get("prompt", "")
        docs = await self.adapter.retrieve_context(prompt)
        state["retrieved_context"] = docs
        return {
            "strategy": self.strategy_type.value,
            "documents_retrieved": len(docs),
            "usage": {"total_tokens": len(str(docs)) // 4},
            "duration_ms": 150.0
        }


class PlanningStrategy(BaseStrategy):
    strategy_type = AmplificationStrategy.PLANNING

    async def execute(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        prompt = payload.get("prompt", "")
        context = state.get("retrieved_context", [])
        plan = await self.adapter.generate_plan(prompt, context)
        state["execution_plan"] = plan
        return {
            "strategy": self.strategy_type.value,
            "steps_planned": len(plan.get("steps", [])),
            "usage": {"total_tokens": 80},
            "duration_ms": 300.0
        }


class ToolGroundedStrategy(BaseStrategy):
    strategy_type = AmplificationStrategy.TOOL_GROUNDED

    async def execute(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        prompt = payload.get("prompt", "")
        plan = state.get("execution_plan", {})
        tools = payload.get("tools", [])
        
        result = await self.adapter.execute_tool_grounded(prompt, plan, tools)
        state["model_output"] = result.get("content", "")
        
        return {
            "strategy": self.strategy_type.value,
            "tools_invoked": len(result.get("tools_used", [])),
            "usage": result.get("usage", {"total_tokens": 0}),
            "duration_ms": result.get("duration_ms", 0.0)
        }


class VerificationStrategy(BaseStrategy):
    strategy_type = AmplificationStrategy.VERIFICATION

    async def execute(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        content = state.get("model_output", "")
        verification = await self.adapter.verify_output(content)
        state["verification_result"] = verification
        return {
            "strategy": self.strategy_type.value,
            "is_valid": verification.get("is_valid", False),
            "usage": {"total_tokens": 40},
            "duration_ms": 100.0
        }


class RepairStrategy(BaseStrategy):
    strategy_type = AmplificationStrategy.REPAIR

    async def execute(self, payload: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
        verification = state.get("verification_result", {})
        if verification.get("is_valid", True):
            return {
                "strategy": self.strategy_type.value,
                "repaired": False,
                "usage": {"total_tokens": 0},
                "duration_ms": 0.0
            }
        
        content = state.get("model_output", "")
        issues = verification.get("issues", [])
        repair_result = await self.adapter.repair_output(content, issues)
        state["model_output"] = repair_result.get("content", "")
        
        return {
            "strategy": self.strategy_type.value,
            "repaired": True,
            "usage": repair_result.get("usage", {"total_tokens": 0}),
            "duration_ms": repair_result.get("duration_ms", 0.0)
        }


def get_strategy_implementation(strategy: AmplificationStrategy, adapter: AmplifiedSubsystemAdapter) -> BaseStrategy:
    """Registry resolver for Amplification Strategies."""
    mapping = {
        AmplificationStrategy.CONTEXT_RETRIEVAL: ContextRetrievalStrategy,
        AmplificationStrategy.PLANNING: PlanningStrategy,
        AmplificationStrategy.TOOL_GROUNDED: ToolGroundedStrategy,
        AmplificationStrategy.VERIFICATION: VerificationStrategy,
        AmplificationStrategy.REPAIR: RepairStrategy,
    }
    impl_class = mapping.get(strategy)
    if not impl_class:
        raise ValueError(f"Unknown Amplification Strategy: {strategy}")
    return impl_class(adapter)