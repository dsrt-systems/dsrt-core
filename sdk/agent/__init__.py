"""
DSRT Agent SDK v1.0 (C1 §17).

Public exports available to agent packages.
"""

from sdk.agent.contract import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentHealth,
    AgentInitializationRequest,
    AgentInitializationResult,
    DSRTAgent,
)
from sdk.agent.interfaces.artifact import ArtifactSDK, SDKArtifact
from sdk.agent.interfaces.benchmark import BenchmarkSDK
from sdk.agent.interfaces.context import ContextSDK, SDKAgentContext
from sdk.agent.interfaces.events import EventSDK
from sdk.agent.interfaces.logging import LoggingSDK
from sdk.agent.interfaces.memory import MemorySDK, SDKMemoryRecord
from sdk.agent.interfaces.model import (
    ModelSDK,
    SDKModelRequest,
    SDKModelResponse,
    SDKModelUsage,
)
from sdk.agent.interfaces.state import StateSDK
from sdk.agent.interfaces.tools import SDKToolResult, ToolSDK
from sdk.agent.interfaces.verification import (
    SDKVerificationResult,
    VerificationSDK,
)
from sdk.agent.sdk import DSRTAgentSDK

from sdk.agent.interfaces.orchestration import (
    OrchestrationSDK,
    SDKDelegationResult,
    SDKNodeInfo,
    SDKPlanInfo,
)
from sdk.agent.interfaces.world import (
    SDKWorldInfo,
    SDKWorldObservation,
    SDKWorldResources,
    WorldSDK,
)


from sdk.agent.interfaces.arena import (
    ArenaSDK,
    SDKArenaResult,
)

__all__ = [
    # Contract
    "DSRTAgent",
    "AgentInitializationRequest",
    "AgentInitializationResult",
    "AgentExecutionRequest",
    "AgentExecutionResult",
    "AgentHealth",
    # Master SDK
    "DSRTAgentSDK",
    # Protocol interfaces
    "ModelSDK",
    "ToolSDK",
    "ContextSDK",
    "MemorySDK",
    "EventSDK",
    "ArtifactSDK",
    "VerificationSDK",
    "StateSDK",
    "LoggingSDK",
    "BenchmarkSDK",
    # DTOs
    "SDKModelRequest",
    "SDKModelResponse",
    "SDKModelUsage",
    "SDKToolResult",
    "SDKAgentContext",
    "SDKMemoryRecord",
    "SDKArtifact",
    "SDKVerificationResult",
    
    "OrchestrationSDK",
    "SDKPlanInfo",
    "SDKNodeInfo",
    "SDKDelegationResult",


    "WorldSDK",
    "SDKWorldInfo",
    "SDKWorldObservation",
    "SDKWorldResources",


    "ArenaSDK",
    "SDKArenaResult",
]