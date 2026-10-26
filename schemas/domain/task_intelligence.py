"""
Phase C11.1: Task Intelligence Schemas

Defines domain schemas for task profiles, classifications, complexity scoring,
risk profiling, constraint sets, dependency graphs, and intelligence requests.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class TaskDomain(str, Enum):
    SOFTWARE_ENGINEERING = "software_engineering"
    DATA_ANALYSIS = "data_analysis"
    CONTENT_GENERATION = "content_generation"
    RESEARCH_SYNTHESIS = "research_synthesis"
    ADMINISTRATIVE = "administrative"
    DEVOPS = "devops"
    MULTI_DOMAIN = "multi_domain"


class TaskIntent(str, Enum):
    CODE_GENERATION = "code_generation"
    BUG_FIXING = "bug_fixing"
    ARCHITECTURE_DESIGN = "architecture_design"
    REFACTORING = "refactoring"
    DATA_EXTRACTION = "data_extraction"
    STATISTICAL_ANALYSIS = "statistical_analysis"
    REASONING_INFERENCE = "reasoning_inference"
    SUMMARIZATION = "summarization"
    TRANSLATION = "translation"
    POLICY_COMPLIANCE = "policy_compliance"
    MULTIMODAL_PROCESSING = "multimodal_processing"


class TaskComplexityLevel(str, Enum):
    TRIVIAL = "trivial"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"
    EXTREME = "extreme"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ConstraintType(str, Enum):
    HARD = "hard"
    SOFT = "soft"


class OptimizationGoal(str, Enum):
    MINIMIZE_COST = "minimize_cost"
    MAXIMIZE_QUALITY = "maximize_quality"
    MAXIMIZE_RELIABILITY = "maximize_reliability"
    MINIMIZE_LATENCY = "minimize_latency"
    BALANCED = "balanced"


class TaskComplexityScore(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: float = Field(..., ge=0.0, le=1.0, description="Normalized overall complexity score [0.0, 1.0]")
    level: TaskComplexityLevel = Field(..., description="Categorical complexity level")
    sub_scores: Dict[str, float] = Field(
        default_factory=dict,
        description="Detailed sub-factor scores (code_density, context_depth, reasoning_steps, structural_breadth, dependency_count)"
    )
    explanation: str = Field("", description="Human-readable explanation of complexity rating")


class TaskRiskProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    overall_level: RiskLevel = Field(..., description="Overall risk category")
    score: float = Field(..., ge=0.0, le=1.0, description="Normalized composite risk score [0.0, 1.0]")
    security_impact: float = Field(0.0, ge=0.0, le=1.0, description="Security vulnerability risk")
    financial_impact: float = Field(0.0, ge=0.0, le=1.0, description="Financial/economic loss risk")
    operational_impact: float = Field(0.0, ge=0.0, le=1.0, description="System stability/operational risk")
    compliance_impact: float = Field(0.0, ge=0.0, le=1.0, description="Regulatory/policy violation risk")
    reversibility: float = Field(1.0, ge=0.0, le=1.0, description="1.0 = fully reversible, 0.0 = completely irreversible")
    hallucination_sensitivity: float = Field(0.5, ge=0.0, le=1.0, description="Sensitivity to incorrect factual claims")
    high_risk_flags: List[str] = Field(default_factory=list, description="Specific identified high-risk indicators")


class TaskConstraint(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str = Field(..., description="Name of the constraint variable")
    value: Any = Field(..., description="Constraint target or limit value")
    constraint_type: ConstraintType = Field(ConstraintType.HARD, description="Hard or soft constraint")
    operator: str = Field("<=", description="Comparison operator: <=, >=, ==, in, not_in")
    description: str = Field("", description="Explanation of why this constraint exists")


class TaskConstraintSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    hard_constraints: List[TaskConstraint] = Field(default_factory=list)
    soft_constraints: List[TaskConstraint] = Field(default_factory=list)
    max_budget_usd: Optional[float] = Field(None, ge=0.0)
    max_latency_ms: Optional[float] = Field(None, ge=0.0)
    min_quality_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    min_reliability_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    allowed_models: Optional[List[str]] = Field(None)
    forbidden_models: Optional[List[str]] = Field(None)
    required_tools: Optional[List[str]] = Field(None)
    security_isolation_level: Optional[str] = Field("standard")


class TaskDependencyNode(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str = Field(..., description="Unique step or node identifier")
    name: str = Field(..., description="Descriptive step name")
    dependency_type: str = Field("sequential", description="sequential, parallel, dynamic, conditional")
    prerequisites: List[str] = Field(default_factory=list, description="List of node_ids that must complete first")


class TaskDependencyGraph(BaseModel):
    model_config = ConfigDict(frozen=True)

    nodes: List[TaskDependencyNode] = Field(default_factory=list)
    edges: List[Dict[str, str]] = Field(default_factory=list, description="List of dicts like {'from': 'A', 'to': 'B'}")
    has_cycles: bool = Field(False)
    execution_order: List[str] = Field(default_factory=list, description="Topological sorting order of node IDs")


class TaskClassification(BaseModel):
    model_config = ConfigDict(frozen=True)

    primary_domain: TaskDomain = Field(..., description="Dominant task domain")
    secondary_domains: List[TaskDomain] = Field(default_factory=list)
    primary_intent: TaskIntent = Field(..., description="Dominant user intent")
    secondary_intents: List[TaskIntent] = Field(default_factory=list)
    confidence: float = Field(1.0, ge=0.0, le=1.0, description="Classification confidence score")


class TaskProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str = Field(..., description="Unique task profile identifier")
    task_id: str = Field(..., description="Associated task identifier")
    organization_id: str = Field(..., description="Tenant / Organization ID")
    classification: TaskClassification
    complexity: TaskComplexityScore
    risk: TaskRiskProfile
    constraints: TaskConstraintSet
    dependencies: TaskDependencyGraph
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class TaskIntelligenceRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    task_id: str = Field(..., description="Unique identifier for the incoming task")
    organization_id: str = Field(..., description="Tenant organization identifier")
    task_description: str = Field(..., description="Full textual task description or prompt")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Structured payload inputs, context, code, etc.")
    provided_constraints: Dict[str, Any] = Field(default_factory=dict, description="User or caller provided explicit constraints")
    optimization_goal: OptimizationGoal = Field(OptimizationGoal.BALANCED, description="Primary optimization target")