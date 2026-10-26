# core/routing/enums.py
"""
C9 enumerations — the categorical vocabulary of intelligence routing.
"""

from enum import Enum


# ── Task domain classification ──────────────────────────────────────

class TaskDomain(str, Enum):
    """High-level task domain for routing context."""
    RESEARCH = "RESEARCH"
    CODING = "CODING"
    DATA_ANALYSIS = "DATA_ANALYSIS"
    WRITING = "WRITING"
    PLANNING = "PLANNING"
    BROWSER_OPERATION = "BROWSER_OPERATION"
    DOCUMENT_PROCESSING = "DOCUMENT_PROCESSING"
    MULTI_AGENT = "MULTI_AGENT"
    LONG_HORIZON = "LONG_HORIZON"
    GENERAL = "GENERAL"


# ── Capability importance ───────────────────────────────────────────

class CapabilityImportance(str, Enum):
    """How critical a capability is to the task."""
    REQUIRED = "REQUIRED"          # Hard constraint — reject if missing
    PREFERRED = "PREFERRED"        # Soft preference — boost if present
    OPTIONAL = "OPTIONAL"          # Nice-to-have — minor boost


# ── Proficiency level ──────────────────────────────────────────────

class ProficiencyLevel(str, Enum):
    """Agent/model proficiency at a capability."""
    EXPERIMENTAL = "EXPERIMENTAL"
    SUPPORTED = "SUPPORTED"
    PRODUCTION = "PRODUCTION"
    CERTIFIED = "CERTIFIED"        # Backed by Arena evidence


# ── Eligibility ────────────────────────────────────────────────────

class EligibilityStatus(str, Enum):
    """Whether a route candidate passed hard-constraint filtering."""
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"


# ── Rejection reason category ──────────────────────────────────────

class RejectionCategory(str, Enum):
    """Why a candidate was rejected."""
    MISSING_CAPABILITY = "MISSING_CAPABILITY"
    POLICY_DENIED = "POLICY_DENIED"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    LATENCY_EXCEEDED = "LATENCY_EXCEEDED"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    WORLD_INCOMPATIBLE = "WORLD_INCOMPATIBLE"
    TOOL_UNAVAILABLE = "TOOL_UNAVAILABLE"
    VERSION_MISMATCH = "VERSION_MISMATCH"


# ── Routing status ─────────────────────────────────────────────────

class RoutingStatus(str, Enum):
    """Lifecycle of a routing decision."""
    PENDING = "PENDING"
    EXTRACTING_REQUIREMENTS = "EXTRACTING_REQUIREMENTS"
    MATCHING_CAPABILITIES = "MATCHING_CAPABILITIES"
    GENERATING_CANDIDATES = "GENERATING_CANDIDATES"
    FILTERING = "FILTERING"
    EVALUATING = "EVALUATING"
    SELECTING = "SELECTING"
    SELECTED = "SELECTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# ── Provider health ────────────────────────────────────────────────

class ProviderHealthStatus(str, Enum):
    """Operational state of a provider (not quality)."""
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    UNKNOWN = "UNKNOWN"


# ── Routing priority ───────────────────────────────────────────────

class RoutingPriority(str, Enum):
    """Weight category for a routing dimension."""
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NONE = "NONE"                  # Ignored in selection


# ── Fallback action types ──────────────────────────────────────────

class FallbackActionType(str, Enum):
    """What the system does when a route fails."""
    RETRY = "RETRY"
    BACKOFF = "BACKOFF"
    SWITCH_MODEL = "SWITCH_MODEL"
    SWITCH_PROVIDER = "SWITCH_PROVIDER"
    SWITCH_TOOL = "SWITCH_TOOL"
    DELEGATE = "DELEGATE"
    REPLAN = "REPLAN"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    ABORT = "ABORT"


# ── Fallback trigger types ─────────────────────────────────────────

class FallbackTriggerType(str, Enum):
    """What event triggers fallback."""
    PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
    PROVIDER_RATE_LIMIT = "PROVIDER_RATE_LIMIT"
    GENERATION_FAILURE = "GENERATION_FAILURE"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    TOOL_FAILURE = "TOOL_FAILURE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    QUALITY_INSUFFICIENT = "QUALITY_INSUFFICIENT"


# ── Adaptive route state ───────────────────────────────────────────

class AdaptiveRouteState(str, Enum):
    """State machine for mid-execution route changes."""
    ACTIVE = "ACTIVE"
    EVALUATING = "EVALUATING"
    SWITCHING = "SWITCHING"
    ESCALATED = "ESCALATED"
    ABORTED = "ABORTED"


# ── Execution stage ────────────────────────────────────────────────

class ExecutionStage(str, Enum):
    """Named stage within a task execution for stage-based routing."""
    PLANNING = "PLANNING"
    RETRIEVAL = "RETRIEVAL"
    ANALYSIS = "ANALYSIS"
    SYNTHESIS = "SYNTHESIS"
    VERIFICATION = "VERIFICATION"
    FINALIZATION = "FINALIZATION"


# ── Evidence source type ───────────────────────────────────────────

class EvidenceSourceType(str, Enum):
    """Where routing evidence originated."""
    ARENA_BENCHMARK = "ARENA_BENCHMARK"
    ARENA_EXPERIMENT = "ARENA_EXPERIMENT"
    PRODUCTION_OBSERVATION = "PRODUCTION_OBSERVATION"
    CAPABILITY_DECLARATION = "CAPABILITY_DECLARATION"
    MANUAL_ASSESSMENT = "MANUAL_ASSESSMENT"


# ── Evidence confidence ────────────────────────────────────────────

class EvidenceConfidence(str, Enum):
    """How much to trust aggregated evidence."""
    HIGH = "HIGH"                  # Many recent, version-matched samples
    MEDIUM = "MEDIUM"              # Moderate samples or partially stale
    LOW = "LOW"                    # Few samples or stale
    INSUFFICIENT = "INSUFFICIENT"  # Not enough data to draw conclusions


# ── Model capability type ──────────────────────────────────────────

class ModelCapabilityType(str, Enum):
    """Standard model-level capabilities for matching."""
    REASONING = "REASONING"
    STRUCTURED_OUTPUT = "STRUCTURED_OUTPUT"
    TOOL_USE = "TOOL_USE"
    VISION = "VISION"
    LONG_CONTEXT = "LONG_CONTEXT"
    CODE_GENERATION = "CODE_GENERATION"
    STREAMING = "STREAMING"
    FUNCTION_CALLING = "FUNCTION_CALLING"
    MULTI_MODAL = "MULTI_MODAL"
    EMBEDDING = "EMBEDDING"


# ── Quality level ──────────────────────────────────────────────────

class QualityLevel(str, Enum):
    """Required quality tier."""
    MINIMUM = "MINIMUM"
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    STRICT = "STRICT"