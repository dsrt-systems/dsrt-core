# core/routing/models.py
"""
C9 — Intelligence Routing Fabric ORM Models.

8 new tables in the ``dsrt`` schema.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """C9 routing models base — self-contained."""

    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> uuid.UUID:
    return uuid.uuid4()


class RoutingPolicyORM(Base):
    __tablename__ = "routing_policies"
    __table_args__ = (
        Index("ix_routing_policies_tenant", "tenant_id"),
        Index("ix_routing_policies_name", "name"),
        {"schema": "dsrt"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_new_id,
    )
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="1",
        server_default="1",
    )
    constraints: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    preferences: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    route_decisions: Mapped[list["RouteDecisionORM"]] = relationship(
        back_populates="routing_policy",
        lazy="selectin",
    )


class RoutingProfileORM(Base):
    __tablename__ = "routing_profiles"
    __table_args__ = (
        Index("ix_routing_profiles_tenant", "tenant_id"),
        UniqueConstraint(
            "name",
            "tenant_id",
            name="uq_routing_profiles_name_tenant",
        ),
        {"schema": "dsrt"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_new_id,
    )
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    quality_priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="MEDIUM",
        server_default="MEDIUM",
    )
    cost_priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="MEDIUM",
        server_default="MEDIUM",
    )
    latency_priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="MEDIUM",
        server_default="MEDIUM",
    )
    reliability_priority: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="MEDIUM",
        server_default="MEDIUM",
    )
    description: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )
    is_builtin: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )

    route_decisions: Mapped[list["RouteDecisionORM"]] = relationship(
        back_populates="routing_profile",
        lazy="selectin",
    )


class RouteDecisionORM(Base):
    __tablename__ = "route_decisions"
    __table_args__ = (
        Index("ix_route_decisions_task", "task_id"),
        Index("ix_route_decisions_execution", "execution_id"),
        Index("ix_route_decisions_status", "status"),
        Index("ix_route_decisions_created", "created_at"),
        {"schema": "dsrt"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_new_id,
    )
    task_id: Mapped[str] = mapped_column(String(255), nullable=False)
    execution_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    routing_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dsrt.routing_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    routing_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dsrt.routing_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    selected_agent_version_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    selected_model_version_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    selected_world_version_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    selected_tools: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    candidate_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    candidates_eligible: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    decision_reason: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evidence_refs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    configuration_hash: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="PENDING",
        server_default="PENDING",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    routing_policy: Mapped["RoutingPolicyORM | None"] = relationship(
        back_populates="route_decisions",
        lazy="selectin",
    )
    routing_profile: Mapped["RoutingProfileORM | None"] = relationship(
        back_populates="route_decisions",
        lazy="selectin",
    )
    candidates: Mapped[list["RouteCandidateORM"]] = relationship(
        back_populates="route_decision",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    cache_entries: Mapped[list["RouteCacheORM"]] = relationship(
        back_populates="route_decision",
        lazy="selectin",
    )


class RouteCandidateORM(Base):
    __tablename__ = "route_candidates"
    __table_args__ = (
        Index("ix_route_candidates_decision", "route_decision_id"),
        Index("ix_route_candidates_eligibility", "eligibility_status"),
        {"schema": "dsrt"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_new_id,
    )
    route_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dsrt.route_decisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_version_id: Mapped[str] = mapped_column(String(255), nullable=False)
    model_version_id: Mapped[str] = mapped_column(String(255), nullable=False)
    world_version_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    tools: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    eligibility_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="ELIGIBLE",
        server_default="ELIGIBLE",
    )
    rejection_reason: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    capability_fit: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    constraint_fit: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evidence_summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evaluation_scores: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )

    route_decision: Mapped["RouteDecisionORM"] = relationship(
        back_populates="candidates",
        lazy="selectin",
    )


class RoutingEvidenceORM(Base):
    __tablename__ = "routing_evidence"
    __table_args__ = (
        Index("ix_routing_evidence_source", "source_type"),
        Index("ix_routing_evidence_model", "model_version"),
        Index("ix_routing_evidence_benchmark", "benchmark_id"),
        Index("ix_routing_evidence_observed", "observed_at"),
        {"schema": "dsrt"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_new_id,
    )
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    benchmark_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    benchmark_version: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    agent_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    world_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sample_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    metrics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )


class FallbackPolicyORM(Base):
    __tablename__ = "fallback_policies"
    __table_args__ = (
        Index("ix_fallback_policies_tenant", "tenant_id"),
        {"schema": "dsrt"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_new_id,
    )
    tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    triggers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    action_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="RETRY",
        server_default="RETRY",
    )
    candidates: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default="3",
    )
    backoff_seconds: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=1.0,
        server_default="1.0",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
        onupdate=_utcnow,
    )


class ProviderHealthORM(Base):
    __tablename__ = "provider_health"
    __table_args__ = (
        Index("ix_provider_health_provider", "provider_id"),
        Index("ix_provider_health_status", "status"),
        Index("ix_provider_health_expires", "expires_at"),
        {"schema": "dsrt"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_new_id,
    )
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="UNKNOWN",
        server_default="UNKNOWN",
    )
    latency_p50_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    latency_p99_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )


class RouteCacheORM(Base):
    __tablename__ = "route_cache"
    __table_args__ = (
        UniqueConstraint("cache_key_hash", name="uq_route_cache_key"),
        Index("ix_route_cache_expires", "expires_at"),
        {"schema": "dsrt"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=_new_id,
    )
    cache_key_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    requirements_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    profile_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_health_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    route_decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("dsrt.route_decisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=_utcnow,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    route_decision: Mapped["RouteDecisionORM"] = relationship(
        back_populates="cache_entries",
        lazy="selectin",
    )