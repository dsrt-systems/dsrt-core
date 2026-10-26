"""
Phase C11.2: Performance Intelligence Schemas

Defines domain schemas for performance evidence, Bayesian/empirical performance estimates,
multidimensional model profiles, configuration profiles, and failure mode analyses.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict


class MetricType(str, Enum):
    QUALITY = "quality"
    RELIABILITY = "reliability"
    LATENCY = "latency"
    COST = "cost"
    TOKEN_EFFICIENCY = "token_efficiency"


class FailureCategory(str, Enum):
    CONTEXT_OVERFLOW = "context_overflow"
    FORMAT_VIOLATION = "format_violation"
    TIMEOUT = "timeout"
    API_RATE_LIMIT = "api_rate_limit"
    TOOL_FAILURE = "tool_failure"
    REASONING_ERROR = "reasoning_error"
    SYSTEM_ERROR = "system_error"
    UNKNOWN = "unknown"


class PerformanceEvidence(BaseModel):
    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(..., description="Unique evidence record identifier")
    model_id: str = Field(..., description="Model identifier evaluated")
    organization_id: str = Field(..., description="Tenant organization identifier")
    domain: str = Field("software_engineering", description="Task domain context")
    intent: str = Field("code_generation", description="Task intent context")
    complexity_level: str = Field("medium", description="Task complexity level context")
    quality_score: float = Field(0.0, ge=0.0, le=1.0, description="Measured quality score [0.0, 1.0]")
    reliability_score: float = Field(1.0, ge=0.0, le=1.0, description="1.0 for success, 0.0 for failure")
    latency_ms: float = Field(0.0, ge=0.0, description="Execution duration in milliseconds")
    input_tokens: int = Field(0, ge=0, description="Number of input/prompt tokens")
    output_tokens: int = Field(0, ge=0, description="Number of generated output tokens")
    cost_usd: float = Field(0.0, ge=0.0, description="Total execution cost in USD")
    error_type: Optional[str] = Field(None, description="Error classification string if failed")
    error_message: Optional[str] = Field(None, description="Detailed error message if failed")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional context or trace references")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PerformanceMetrics(BaseModel):
    model_config = ConfigDict(frozen=True)

    quality_mean: float = Field(..., ge=0.0, le=1.0, description="Estimated expected quality score")
    quality_std: float = Field(0.0, ge=0.0, description="Standard deviation of quality score")
    reliability_rate: float = Field(..., ge=0.0, le=1.0, description="Bayesian/empirical expected success rate")
    latency_p50_ms: float = Field(..., ge=0.0, description="Median latency in milliseconds")
    latency_p90_ms: float = Field(..., ge=0.0, description="90th percentile latency in milliseconds")
    latency_p99_ms: float = Field(..., ge=0.0, description="99th percentile latency in milliseconds")
    cost_mean_usd: float = Field(0.0, ge=0.0, description="Average cost per task execution")
    token_efficiency: float = Field(0.0, ge=0.0, description="Tokens generated per USD")
    sample_count: int = Field(0, ge=0, description="Total number of evidence data points")
    confidence_interval_low: float = Field(0.0, ge=0.0, le=1.0, description="Lower 95% quality bound")
    confidence_interval_high: float = Field(1.0, ge=0.0, le=1.0, description="Upper 95% quality bound")


class FailureModeDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: FailureCategory
    frequency: int = Field(..., ge=0, description="Occurrences count")
    percentage: float = Field(..., ge=0.0, le=1.0, description="Fraction of total model errors")
    average_latency_ms: float = Field(0.0, ge=0.0)
    common_triggers: List[str] = Field(default_factory=list)
    recommended_mitigation: str = Field("", description="Actionable strategy adjustment recommendation")


class FailureAnalysisResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    total_executions: int = Field(0, ge=0)
    total_failures: int = Field(0, ge=0)
    overall_failure_rate: float = Field(0.0, ge=0.0, le=1.0)
    breakdown: List[FailureModeDetail] = Field(default_factory=list)
    primary_vulnerability: Optional[FailureCategory] = Field(None)


class PerformanceProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profile_id: str = Field(..., description="Unique performance profile identifier")
    model_id: str = Field(..., description="Evaluated AI model identifier")
    organization_id: str = Field(..., description="Tenant organization identifier")
    domain: str = Field("all", description="Target domain, or 'all'")
    intent: str = Field("all", description="Target intent, or 'all'")
    complexity_level: str = Field("all", description="Target complexity level, or 'all'")
    metrics: PerformanceMetrics
    failure_analysis: FailureAnalysisResult
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConfigurationProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    config_id: str = Field(..., description="Unique configuration profile identifier")
    organization_id: str = Field(..., description="Tenant organization identifier")
    model_id: str = Field(..., description="Base model identifier")
    hyperparameters: Dict[str, Any] = Field(default_factory=dict, description="Temperature, top_p, max_tokens, etc.")
    strategy_overrides: Dict[str, Any] = Field(default_factory=dict, description="Amplification/verification strategies")
    system_prompt_hash: str = Field("", description="Fingerprint of system prompt template")
    performance_summary: Dict[str, float] = Field(default_factory=dict, description="Cached performance metrics summary")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PerformanceQuery(BaseModel):
    model_config = ConfigDict(frozen=True)

    model_id: str
    domain: Optional[str] = None
    intent: Optional[str] = None
    complexity_level: Optional[str] = None
    min_samples: int = Field(1, ge=1)