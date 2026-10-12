"""
DSRT Model Fabric Contracts (C2 §9, §10, §11, §19).

The canonical, provider-neutral contracts that every provider adapter translates
to and from. These schemas are the frozen spine of the Model Fabric — their
public shape MUST NOT change without a Model Contract version bump.

Design principles:
- Provider-neutral: no OpenAI/Gemini/Anthropic concepts leak in.
- Multi-modal: canonical messages support text + image + audio + document.
- Reproducible: every request carries a stable request_id and context hash hooks.
- Auditable: usage, routing decisions, and errors all have dedicated contracts.
- Cost-honest: estimated_cost_usd and provider_reported_cost_usd NEVER merge.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field, field_validator

from schemas.domain.base import DSRTImmutableSchema, DSRTSchema
from schemas.domain.enums import (
    CredentialStatus,
    CredentialType,
    FinishReason,
    MessageContentType,
    MessageRole,
    ModelErrorCode,
    ModelModality,
    ProviderHealthStatus,
    ReasoningEffort,
    RetryClassification,
    RoutingReasonCode,
    StreamEventType,
    ToolCallMode,
)


# =============================================================================
# Canonical Messages (multi-modal)
# =============================================================================


class MessageContentPart(DSRTSchema):
    """One part of a multi-part message (text, image, audio, tool result).

    Provider adapters are responsible for translating these parts into
    the provider's native message format.
    """

    type: MessageContentType
    text: str | None = None
    image_url: str | None = None
    image_bytes_base64: str | None = None
    image_mime_type: str | None = None
    audio_base64: str | None = None
    audio_mime_type: str | None = None
    tool_call_id: str | None = None
    tool_result: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("type")
    @classmethod
    def _validate_content_consistency(
        cls, v: MessageContentType,
    ) -> MessageContentType:
        # Content-type consistency is enforced at the Message level via its own validator.
        return v


class ModelMessage(DSRTSchema):
    """A canonical message in a model request (C2 §9).

    Supports multi-part content for multi-modal models while remaining
    directly usable with simple text-only models.
    """

    role: MessageRole
    content: str | list[MessageContentPart]
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def _validate_content(
        cls, v: str | list[MessageContentPart],
    ) -> str | list[MessageContentPart]:
        if isinstance(v, str):
            if not v.strip():
                raise ValueError("Message content string must not be empty.")
            return v
        if isinstance(v, list) and len(v) == 0:
            raise ValueError("Message content list must not be empty.")
        return v


# =============================================================================
# Tool Definitions and Tool Calls
# =============================================================================


class ToolParameterSchema(DSRTSchema):
    """JSON-Schema-compatible parameter definition for a tool."""

    type: str = "object"
    properties: dict[str, Any] = Field(default_factory=dict)
    required: list[str] = Field(default_factory=list)
    additional_properties: bool = False


class ToolDefinition(DSRTSchema):
    """Provider-neutral tool definition the model may invoke (C2 §38).

    The model only sees the tool's name, description, and parameter schema.
    Actual execution is performed by Core's Tool Runtime (arrives in C3).
    """

    name: str = Field(min_length=1, max_length=200, pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$")
    description: str = Field(min_length=1, max_length=2000)
    parameters: ToolParameterSchema = Field(default_factory=ToolParameterSchema)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(DSRTImmutableSchema):
    """A tool invocation emitted by a model (C2 §38).

    DSRT normalizes provider-specific tool-call formats into this shape.
    The id is stable within a single response and used by subsequent
    tool-result messages.
    """

    id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw_arguments_text: str | None = None


# =============================================================================
# Agent-Expressed Model Policy and Requirements
# =============================================================================


class ModelRequirements(DSRTSchema):
    """Agent-expressed model requirements (C2 §16, §46).

    These are preferences, not authority. The Model Router may ignore them
    if policy or availability requires it, but every rejection is audited.
    """

    required_capabilities: list[str] = Field(default_factory=list)
    preferred_capabilities: list[str] = Field(default_factory=list)
    required_modalities: list[ModelModality] = Field(default_factory=list)

    minimum_context_tokens: int | None = Field(default=None, gt=0)
    minimum_output_tokens: int | None = Field(default=None, gt=0)

    supports_tool_calling: bool | None = None
    supports_structured_output: bool | None = None
    supports_streaming: bool | None = None
    supports_vision: bool | None = None
    supports_reasoning: bool | None = None

    maximum_latency_ms: int | None = Field(default=None, gt=0)
    maximum_cost_usd: Decimal | None = Field(default=None, ge=0)


class ModelPolicy(DSRTSchema):
    """Routing policy applied to a model request (C2 §18, §31).

    Policies express hard constraints (allowed/blocked models) plus soft
    optimization targets (prefer_lower_cost, prefer_lower_latency).
    """

    policy_id: str | None = None
    allowed_providers: list[str] = Field(default_factory=list)
    blocked_providers: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    blocked_models: list[str] = Field(default_factory=list)
    preferred_models: list[str] = Field(default_factory=list)
    fallback_models: list[str] = Field(default_factory=list)

    allow_byok: bool = True
    allow_managed: bool = True
    allow_enterprise: bool = True

    maximum_cost_usd: Decimal | None = Field(default=None, ge=0)
    maximum_latency_ms: int | None = Field(default=None, gt=0)

    prefer_lower_cost: bool = False
    prefer_lower_latency: bool = False


# =============================================================================
# ModelRequest — the canonical provider-neutral request (C2 §9)
# =============================================================================


class ModelRequest(DSRTSchema):
    """Canonical, provider-neutral model request (C2 §9).

    Every provider adapter translates this into its native format.
    The request carries execution identity so usage, errors, and routing
    decisions can be correlated back to the DSRT trajectory.
    """

    # Identity + correlation
    request_id: str = Field(min_length=1, max_length=32)
    execution_id: str = Field(min_length=1, max_length=32)
    task_id: str = Field(min_length=1, max_length=32)
    organization_id: str = Field(min_length=1, max_length=32)
    agent_id: str | None = None

    # Idempotency and retry correlation
    idempotency_key: str | None = Field(default=None, max_length=128)
    attempt: int = Field(default=1, ge=1)

    # What the agent is trying to accomplish (semantic hint used by routing)
    purpose: str = Field(min_length=1, max_length=200)

    # The conversation
    messages: list[ModelMessage] = Field(min_length=1)
    system_context: dict[str, Any] | None = None

    # Tool calling
    tools: list[ToolDefinition] | None = None
    tool_choice: str | None = None  # "auto" | "none" | "required" | specific tool name
    tool_call_mode: ToolCallMode | None = None

    # Structured output
    response_schema: dict[str, Any] | None = None
    response_mime_type: str | None = None

    # Generation parameters
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, ge=0.0, le=1.0)
    max_output_tokens: int | None = Field(default=None, gt=0)
    stop_sequences: list[str] | None = None
    seed: int | None = None

    # Reasoning / modality controls
    reasoning_effort: ReasoningEffort | None = None
    modalities: list[ModelModality] = Field(default_factory=lambda: [ModelModality.TEXT])

    # Agent / policy preferences
    requirements: ModelRequirements | None = None
    model_policy: ModelPolicy | None = None

    # Streaming hint (adapter chooses actual transport)
    stream: bool = False

    # Deadline / cancellation
    timeout_seconds: float | None = Field(default=None, gt=0.0)

    # Free-form metadata (never contains credentials)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("messages")
    @classmethod
    def _validate_messages_not_empty(cls, v: list[ModelMessage]) -> list[ModelMessage]:
        if not v:
            raise ValueError("ModelRequest.messages must contain at least one message.")
        return v


class TokenCountRequest(DSRTSchema):
    """Request to count tokens for a prospective ModelRequest (C2 §8)."""

    messages: list[ModelMessage] = Field(min_length=1)
    tools: list[ToolDefinition] | None = None
    system_context: dict[str, Any] | None = None


# =============================================================================
# Usage, Cost, and Response (C2 §10, §11, §36)
# =============================================================================


class Usage(DSRTImmutableSchema):
    """Normalized usage record (C2 §11).

    Rule: estimated_cost_usd MUST NEVER be presented as provider_reported_cost_usd.
    """

    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cached_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

    estimated_cost_usd: Decimal | None = Field(default=None, ge=0)
    provider_reported_cost_usd: Decimal | None = Field(default=None, ge=0)


class CostBreakdown(DSRTImmutableSchema):
    """Granular cost accounting separated by category (C2 §36).

    DSRT distinguishes:
      - provider_cost_usd: what the provider charged
      - estimated_cost_usd: what DSRT computed from token counts + pricing
      - dsrt_platform_cost_usd: DSRT infrastructure overhead
      - customer_charge_usd: billing-layer concern, kept here as an audit field
    """

    provider_cost_usd: Decimal | None = Field(default=None, ge=0)
    estimated_cost_usd: Decimal | None = Field(default=None, ge=0)
    dsrt_platform_cost_usd: Decimal | None = Field(default=None, ge=0)
    customer_charge_usd: Decimal | None = Field(default=None, ge=0)


class TokenCountResponse(DSRTImmutableSchema):
    """Response from a token-count request (C2 §8)."""

    input_tokens: int = Field(ge=0)
    tool_tokens: int = Field(default=0, ge=0)
    system_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(ge=0)
    model_identifier: str
    is_estimate: bool = True  # True unless provider confirmed the count


# =============================================================================
# ModelResponse — the canonical provider-neutral response (C2 §10)
# =============================================================================


class ModelResponse(DSRTImmutableSchema):
    """Canonical, provider-neutral model response (C2 §10)."""

    request_id: str
    model_id: str
    provider_id: str
    model_identifier: str  # provider-side identifier for reproducibility

    output: str | None = None
    structured_output: dict[str, Any] | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)

    finish_reason: FinishReason = FinishReason.COMPLETED
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = Field(ge=0)

    # Provenance hooks for the C2 benchmark and Arena (C8)
    created_at: datetime
    attempt: int = Field(default=1, ge=1)

    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# StreamEvent (C2 §37)
# =============================================================================


class StreamEvent(DSRTImmutableSchema):
    """One event in a normalized model stream (C2 §37)."""

    request_id: str
    event_type: StreamEventType
    sequence: int = Field(ge=0)

    # Deltas (one of these is populated based on event_type)
    text_delta: str | None = None
    reasoning_delta: str | None = None
    tool_call_delta: dict[str, Any] | None = None
    structured_output_delta: dict[str, Any] | None = None
    usage_delta: Usage | None = None

    # Terminal event payloads
    finish_reason: FinishReason | None = None
    error_code: ModelErrorCode | None = None
    error_message: str | None = None

    created_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Provider Health (C2 §30)
# =============================================================================


class ProviderHealth(DSRTImmutableSchema):
    """Health observation for a provider or specific model (C2 §30)."""

    provider_id: str
    model_id: str | None = None
    status: ProviderHealthStatus
    observed_at: datetime

    # Rolling-window health signals
    error_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    avg_latency_ms: float | None = Field(default=None, ge=0.0)
    rate_limit_remaining: int | None = Field(default=None, ge=0)
    rate_limit_reset_at: datetime | None = None

    message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Model Error (normalized across providers) (C2 §27, §35)
# =============================================================================


class ModelError(DSRTImmutableSchema):
    """Normalized model-fabric error (C2 §27, §35).

    Provider-specific error context is preserved under provider_metadata
    but the primary code is drawn from the DSRT ModelErrorCode taxonomy.
    """

    code: ModelErrorCode
    message: str
    retry_classification: RetryClassification
    provider_id: str | None = None
    model_id: str | None = None
    request_id: str | None = None
    attempt: int = Field(default=1, ge=1)
    provider_status_code: int | None = None
    provider_error_type: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    retry_after_seconds: float | None = Field(default=None, ge=0.0)


# =============================================================================
# Routing Decision (audit trail — C2 §19)
# =============================================================================


class RejectedCandidate(DSRTImmutableSchema):
    """A model that was considered but not selected.

    Every rejection records a specific reason code so the routing audit
    trail is machine-readable.
    """

    model_id: str
    provider_id: str
    model_identifier: str
    reason_codes: list[RoutingReasonCode]
    details: dict[str, Any] = Field(default_factory=dict)


class RoutingDecision(DSRTImmutableSchema):
    """Deterministic routing decision record (C2 §19).

    Every model request produces exactly one RoutingDecision, persisted for
    later audit by Arena (C8) and Intelligence Routing (C9).
    """

    request_id: str
    selected_model_id: str
    selected_provider_id: str
    selected_model_identifier: str

    reason_codes: list[RoutingReasonCode]
    candidates_considered: list[str]  # model_ids considered
    rejected_candidates: list[RejectedCandidate] = Field(default_factory=list)

    policy_id: str | None = None
    requirements_snapshot: ModelRequirements | None = None
    model_policy_snapshot: ModelPolicy | None = None

    decided_at: datetime
    decision_latency_ms: int = Field(ge=0)

    metadata: dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Credential Reference (C2 §12, §14)
# =============================================================================


class CredentialReference(DSRTImmutableSchema):
    """Opaque reference to a stored credential (C2 §14).

    This object may safely appear in logs/events because it carries NO secret
    material. Only the id, owner, provider, and lifecycle metadata are exposed.
    """

    id: str
    organization_id: str
    provider_id: str
    credential_type: CredentialType
    status: CredentialStatus
    label: str | None = None
    created_at: datetime
    rotated_at: datetime | None = None
    last_used_at: datetime | None = None
    expires_at: datetime | None = None