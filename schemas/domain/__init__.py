"""DSRT Domain Schemas — the canonical type system for DSRT Core."""

from schemas.domain.enums import (
    # C1 Enums
    AgentStatus,
    AgentVersionStatus,
    ArtifactType,
    ErrorCode,
    EventType,
    ExecutionStatus,
    OrganizationRole,
    OrganizationStatus,
    ProviderStatus,
    ProviderType,
    RiskLevel,
    TaskStatus,
    UserStatus,
    VerificationStatus,
    # C2 Model Fabric Enums
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
    # C3 Tool & Environment Fabric Enums
    ApprovalStatus,
    EnvironmentHealthStatus,
    EnvironmentStatus,
    EnvironmentType,
    FilesystemAccessMode,
    NetworkMode,
    ObservationType,
    SideEffectClass,
    ToolExecutionStatus,
    ToolHealthStatus,
    ToolRiskLevel,
    ToolStatus,
    WorldStatus,
)

from schemas.domain.base import (
    DSRTImmutableSchema,
    DSRTSchema,
    TimestampedSchema,
)

from schemas.domain.organization import (
    Organization,
    OrganizationCreate,
    OrganizationMember,
    User,
    UserCreate,
)

from schemas.domain.capability import Capability, CapabilityCreate

from schemas.domain.agent import (
    Agent,
    AgentIdentity,
    AgentManifest,
    AgentPermissions,
    AgentRegistrationRequest,
    AgentRequirements,
    AgentVersion,
    BrowserPermission,
    ExternalActionsPermission,
    FilesystemPermission,
    NetworkPermission,
)

from schemas.domain.task import Task, TaskConstraints, TaskCreate

from schemas.domain.execution import (
    Execution,
    ExecutionError,
    ResourceLimits,
)

from schemas.domain.event import ExecutionEvent, ExecutionEventCreate

from schemas.domain.artifact import Artifact, ArtifactCreate

from schemas.domain.verification import (
    VerificationCheck,
    VerificationRequest,
    VerificationResult,
    VerificationRun,
)

from schemas.domain.usage import UsageRecord, UsageRecordCreate

from schemas.domain.provider import Model, ModelCreate, Provider, ProviderCreate

# C2 Model Fabric Contracts
from schemas.domain.model_fabric import (
    CostBreakdown,
    CredentialReference,
    MessageContentPart,
    ModelError,
    ModelMessage,
    ModelPolicy,
    ModelRequest,
    ModelRequirements,
    ModelResponse,
    ProviderHealth,
    RejectedCandidate,
    RoutingDecision,
    StreamEvent,
    TokenCountRequest,
    TokenCountResponse,
    ToolCall,
    ToolDefinition,
    ToolParameterSchema,
    Usage,
)

from schemas.domain.context_compiler import (
    CompiledContext,
    ContextBudget,
    ContextProvenanceItem,
)

from schemas.domain.session import (
    ModelCheckpoint,
    ModelCheckpointCreate,
    ModelSession,
    ModelSessionCreate,
)
from schemas.domain.retry import RetryPolicy

# C3 Tool & Environment Fabric Contracts
from schemas.domain.approval import (
    ApprovalCreate,
    ApprovalDecision,
    ApprovalDecisionCreate,
    ApprovalRequest,
)
from schemas.domain.environment import (
    Environment,
    EnvironmentFilesystemPolicy,
    EnvironmentHealth,
    EnvironmentIdentity,
    EnvironmentInstance,
    EnvironmentManifest,
    EnvironmentNetworkPolicy,
    EnvironmentResourceLimits,
    EnvironmentResources,
    EnvironmentSnapshot,
    EnvironmentVersion,
)
from schemas.domain.tool import (
    Tool,
    ToolBrowserPermission,
    ToolCapabilityDeclaration,
    ToolCapabilityLink,
    ToolContext,
    ToolCredentialPermission,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolFilesystemPermission,
    ToolHealth,
    ToolIdentity,
    ToolInitializationResult,
    ToolLimits,
    ToolManifest,
    ToolNetworkPermission,
    ToolObservation,
    ToolObservationCreate,
    ToolPermissionDeclaration,
    ToolRetryPolicy,
    ToolUsage,
    ToolVersion,
)
from schemas.domain.world import (
    World,
    WorldHealth,
    WorldIdentity,
    WorldInstance,
    WorldManifest,
    WorldObservation,
    WorldPolicy,
    WorldSnapshot,
    WorldVersion,
)

# --- C4 Context & Memory Fabric ---
from schemas.domain.memory import (
    Memory,
    MemoryConflict,
    MemoryCreate,
    MemoryLink,
    MemoryLinkCreate,
    MemoryQuery,
    MemoryRetrievalResponse,
    MemoryRetrievalResult,
    MemorySource,
    MemoryUpdate,
    MemoryVersion,
)
from schemas.domain.context import (
    ContextBuildRequest,
    ContextBuildResult,
    ContextProfile,
)


# --- C6 Verification & Reliability Fabric ---
from schemas.domain.verification import (
    C6RecoveryDecision,
    C6VerificationResult,
    Claim,
    ClaimVerification,
    ConfidenceRecord,
    Constraint,
    ConstraintResult,
    Evidence,
    EvidenceReference,
    FailureAction,
    ReliabilityIncident,
    Requirement,
    ReviewRequest,
    VerificationCheckResult,
    VerificationPolicy,
    VerificationThresholds,
)

__all__ = [
    # --- C1 Enums ---
    "AgentStatus",
    "AgentVersionStatus",
    "ArtifactType",
    "ErrorCode",
    "EventType",
    "ExecutionStatus",
    "OrganizationRole",
    "OrganizationStatus",
    "ProviderStatus",
    "ProviderType",
    "RiskLevel",
    "TaskStatus",
    "UserStatus",
    "VerificationStatus",
    # --- C2 Model Fabric Enums ---
    "CredentialStatus",
    "CredentialType",
    "FinishReason",
    "MessageContentType",
    "MessageRole",
    "ModelErrorCode",
    "ModelModality",
    "ProviderHealthStatus",
    "ReasoningEffort",
    "RetryClassification",
    "RoutingReasonCode",
    "StreamEventType",
    "ToolCallMode",
    # --- C3 Tool & Environment Fabric Enums ---
    "ApprovalStatus",
    "EnvironmentHealthStatus",
    "EnvironmentStatus",
    "EnvironmentType",
    "FilesystemAccessMode",
    "NetworkMode",
    "ObservationType",
    "SideEffectClass",
    "ToolExecutionStatus",
    "ToolHealthStatus",
    "ToolRiskLevel",
    "ToolStatus",
    "WorldStatus",
    # --- Base ---
    "DSRTSchema",
    "DSRTImmutableSchema",
    "TimestampedSchema",
    # --- Organization ---
    "Organization",
    "OrganizationCreate",
    "User",
    "UserCreate",
    "OrganizationMember",
    # --- Capability ---
    "Capability",
    "CapabilityCreate",
    # --- Agent ---
    "AgentIdentity",
    "AgentRequirements",
    "AgentPermissions",
    "NetworkPermission",
    "FilesystemPermission",
    "BrowserPermission",
    "ExternalActionsPermission",
    "AgentManifest",
    "AgentRegistrationRequest",
    "Agent",
    "AgentVersion",
    # --- Task / Execution ---
    "Task",
    "TaskCreate",
    "TaskConstraints",
    "Execution",
    "ResourceLimits",
    "ExecutionError",
    # --- Event ---
    "ExecutionEvent",
    "ExecutionEventCreate",
    # --- Artifact ---
    "Artifact",
    "ArtifactCreate",
    # --- Verification ---
    "VerificationRun",
    "VerificationResult",
    "VerificationCheck",
    "VerificationRequest",
    # --- Usage ---
    "UsageRecord",
    "UsageRecordCreate",
    # --- Provider ---
    "Provider",
    "ProviderCreate",
    "Model",
    "ModelCreate",
    # --- C2 Model Fabric Contracts ---
    "CostBreakdown",
    "CredentialReference",
    "MessageContentPart",
    "ModelError",
    "ModelMessage",
    "ModelPolicy",
    "ModelRequest",
    "ModelRequirements",
    "ModelResponse",
    "ProviderHealth",
    "RejectedCandidate",
    "RoutingDecision",
    "StreamEvent",
    "TokenCountRequest",
    "TokenCountResponse",
    "ToolCall",
    "ToolDefinition",
    "ToolParameterSchema",
    "Usage",
    # --- C2 Context Compiler ---
    "CompiledContext",
    "ContextBudget",
    "ContextProvenanceItem",
    # --- C2 Sessions / Retry ---
    "ModelCheckpoint",
    "ModelCheckpointCreate",
    "ModelSession",
    "ModelSessionCreate",
    "RetryPolicy",
    # --- C3 Tool & Environment Fabric ---
    "ApprovalCreate",
    "ApprovalDecision",
    "ApprovalDecisionCreate",
    "ApprovalRequest",
    "Environment",
    "EnvironmentFilesystemPolicy",
    "EnvironmentHealth",
    "EnvironmentIdentity",
    "EnvironmentInstance",
    "EnvironmentManifest",
    "EnvironmentNetworkPolicy",
    "EnvironmentResourceLimits",
    "EnvironmentResources",
    "EnvironmentSnapshot",
    "EnvironmentVersion",
    "Tool",
    "ToolBrowserPermission",
    "ToolCapabilityDeclaration",
    "ToolCapabilityLink",
    "ToolContext",
    "ToolCredentialPermission",
    "ToolExecutionError",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    "ToolFilesystemPermission",
    "ToolHealth",
    "ToolIdentity",
    "ToolInitializationResult",
    "ToolLimits",
    "ToolManifest",
    "ToolNetworkPermission",
    "ToolObservation",
    "ToolObservationCreate",
    "ToolPermissionDeclaration",
    "ToolRetryPolicy",
    "ToolUsage",
    "ToolVersion",
    "World",
    "WorldHealth",
    "WorldIdentity",
    "WorldInstance",
    "WorldManifest",
    "WorldObservation",
    "WorldPolicy",
    "WorldSnapshot",
    "WorldVersion",


    # --- C4 Context & Memory Fabric ---
    "Memory",
    "MemoryConflict",
    "MemoryCreate",
    "MemoryLink",
    "MemoryLinkCreate",
    "MemoryQuery",
    "MemoryRetrievalResponse",
    "MemoryRetrievalResult",
    "MemorySource",
    "MemoryUpdate",
    "MemoryVersion",
    "ContextBuildRequest",
    "ContextBuildResult",
    "ContextProfile",

    # --- C6 Verification & Reliability Fabric ---
    "C6RecoveryDecision",
    "C6VerificationResult",
    "Claim",
    "ClaimVerification",
    "ConfidenceRecord",
    "Constraint",
    "ConstraintResult",
    "Evidence",
    "EvidenceReference",
    "FailureAction",
    "ReliabilityIncident",
    "Requirement",
    "ReviewRequest",
    "VerificationCheckResult",
    "VerificationPolicy",
    "VerificationThresholds",
]