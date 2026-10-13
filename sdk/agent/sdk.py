"""
DSRTAgentSDK — the master SDK object injected into every Agent (C1 §17).

Every DSRT Agent receives exactly one instance of this SDK during initialize().
The SDK is the ONLY surface through which an Agent interacts with Core.

Agents must NEVER:
- Import from `core.storage`, `core.repositories`, `core.kernel`
- Import provider SDKs (openai, anthropic, google, etc.)
- Access the database, Redis, or filesystem directly
- Bypass the SDK to reach Core internals

The Core team can replace ANY implementation behind these protocols without
touching a single line of agent code — provided the Protocol contracts hold.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sdk.agent.interfaces.artifact import ArtifactSDK
from sdk.agent.interfaces.benchmark import BenchmarkSDK
from sdk.agent.interfaces.context import ContextSDK
from sdk.agent.interfaces.events import EventSDK
from sdk.agent.interfaces.logging import LoggingSDK
from sdk.agent.interfaces.memory import MemorySDK
from sdk.agent.interfaces.model import ModelSDK
from sdk.agent.interfaces.orchestration import OrchestrationSDK
from sdk.agent.interfaces.state import StateSDK
from sdk.agent.interfaces.tools import ToolSDK
from sdk.agent.interfaces.verification import VerificationSDK


@dataclass(frozen=True)
class DSRTAgentSDK:
    """The frozen SDK instance provided to every DSRT Agent."""

    model: ModelSDK
    tools: ToolSDK
    context: ContextSDK
    memory: MemorySDK
    events: EventSDK
    artifacts: ArtifactSDK
    verification: VerificationSDK
    state: StateSDK
    logging: LoggingSDK
    benchmark: BenchmarkSDK
    orchestration: OrchestrationSDK | None = None

    # SDK version stamped at injection time — agents can gate on this.
    sdk_version: str = "1.0.0"
    contract_version: str = "1.0"