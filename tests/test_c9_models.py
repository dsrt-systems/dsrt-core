# tests/test_c9_models.py
"""
C9.2 — Database & ORM Models.

Tests all 8 ORM models for the Intelligence Routing Fabric.
Validates table names, schemas, column types, defaults (metadata),
relationships, indexes, and constraints.

NOTE: SQLAlchemy 2.0 ``mapped_column(default=...)`` sets INSERT defaults,
not Python ``__init__`` defaults.  We test column metadata directly.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from core.routing.models import (
    FallbackPolicyORM,
    ProviderHealthORM,
    RouteCacheORM,
    RouteCandidateORM,
    RouteDecisionORM,
    RoutingEvidenceORM,
    RoutingPolicyORM,
    RoutingProfileORM,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _col(model, name):
    """Get a column object by name from a model's table."""
    return {c.name: c for c in model.__table__.columns}[name]


def _col_default(model, name):
    """Get the Python-side default value from a column's ColumnDefault."""
    col = _col(model, name)
    if col.default is not None and col.default.arg is not None:
        arg = col.default.arg
        if callable(arg):
            return arg
        return arg
    return None


def _col_server_default(model, name):
    """Get the server_default text from a column."""
    col = _col(model, name)
    if col.server_default is not None:
        arg = col.server_default.arg
        if hasattr(arg, "text"):
            return arg.text
        return str(arg)
    return None


# ════════════════════════════════════════════════════════════════════
# 1. ROUTING POLICIES
# ════════════════════════════════════════════════════════════════════


class TestRoutingPolicyORM:

    def test_table_name_and_schema(self):
        assert RoutingPolicyORM.__tablename__ == "routing_policies"
        assert RoutingPolicyORM.__table_args__[-1]["schema"] == "dsrt"

    def test_instantiation(self):
        p = RoutingPolicyORM(
            name="Enterprise Default",
            version="1",
            description="",
            is_active=True,
        )
        assert p.name == "Enterprise Default"
        assert p.version == "1"
        assert p.is_active is True

    def test_instantiation_full(self):
        p = RoutingPolicyORM(
            tenant_id="org_123",
            name="Strict Policy",
            version="2",
            constraints={"allowed_models": ["model_a"]},
            preferences={"quality_priority": "HIGH"},
            description="Enterprise strict routing",
            is_active=True,
        )
        assert p.tenant_id == "org_123"
        assert p.constraints["allowed_models"] == ["model_a"]
        assert p.preferences["quality_priority"] == "HIGH"

    def test_version_default_metadata(self):
        assert _col_default(RoutingPolicyORM, "version") == "1"
        assert _col_server_default(RoutingPolicyORM, "version") == "1"

    def test_is_active_default_metadata(self):
        assert _col_default(RoutingPolicyORM, "is_active") is True

    def test_uuid_primary_key(self):
        col = _col(RoutingPolicyORM, "id")
        assert str(col.type) == "UUID"

    def test_jsonb_columns(self):
        assert str(_col(RoutingPolicyORM, "constraints").type) == "JSONB"
        assert str(_col(RoutingPolicyORM, "preferences").type) == "JSONB"

    def test_timestamp_columns_tz_aware(self):
        assert _col(RoutingPolicyORM, "created_at").type.timezone is True
        assert _col(RoutingPolicyORM, "updated_at").type.timezone is True

    def test_indexes_exist(self):
        index_names = {idx.name for idx in RoutingPolicyORM.__table__.indexes}
        assert "ix_routing_policies_tenant" in index_names
        assert "ix_routing_policies_name" in index_names


# ════════════════════════════════════════════════════════════════════
# 2. ROUTING PROFILES
# ════════════════════════════════════════════════════════════════════


class TestRoutingProfileORM:

    def test_table_name_and_schema(self):
        assert RoutingProfileORM.__tablename__ == "routing_profiles"
        assert RoutingProfileORM.__table_args__[-1]["schema"] == "dsrt"

    def test_instantiation(self):
        p = RoutingProfileORM(
            name="FAST",
            quality_priority="HIGH",
            cost_priority="HIGH",
            latency_priority="HIGH",
            reliability_priority="MEDIUM",
            description="Optimise for speed",
            is_builtin=False,
        )
        assert p.name == "FAST"
        assert p.quality_priority == "HIGH"

    def test_priority_defaults_metadata(self):
        for col_name in (
            "quality_priority",
            "cost_priority",
            "latency_priority",
            "reliability_priority",
        ):
            assert _col_default(RoutingProfileORM, col_name) == "MEDIUM"
            assert _col_server_default(RoutingProfileORM, col_name) == "MEDIUM"

    def test_is_builtin_default_metadata(self):
        assert _col_default(RoutingProfileORM, "is_builtin") is False

    def test_unique_constraint(self):
        constraints = [
            c
            for c in RoutingProfileORM.__table__.constraints
            if hasattr(c, "name") and c.name == "uq_routing_profiles_name_tenant"
        ]
        assert len(constraints) == 1

    def test_indexes_exist(self):
        index_names = {idx.name for idx in RoutingProfileORM.__table__.indexes}
        assert "ix_routing_profiles_tenant" in index_names


# ════════════════════════════════════════════════════════════════════
# 3. ROUTE DECISIONS
# ════════════════════════════════════════════════════════════════════


class TestRouteDecisionORM:

    def test_table_name_and_schema(self):
        assert RouteDecisionORM.__tablename__ == "route_decisions"
        assert RouteDecisionORM.__table_args__[-1]["schema"] == "dsrt"

    def test_instantiation(self):
        d = RouteDecisionORM(
            task_id="task_001",
            status="PENDING",
            candidate_count=0,
            candidates_eligible=0,
        )
        assert d.task_id == "task_001"
        assert d.status == "PENDING"

    def test_instantiation_full(self):
        policy_id = uuid.uuid4()
        profile_id = uuid.uuid4()
        d = RouteDecisionORM(
            task_id="task_002",
            execution_id="exec_001",
            routing_policy_id=policy_id,
            routing_profile_id=profile_id,
            selected_agent_version_id="agent_v1",
            selected_model_version_id="model_v1",
            selected_world_version_id="world_v1",
            selected_tools=["web.search", "web.retrieve"],
            candidate_count=5,
            candidates_eligible=3,
            decision_reason={"primary": "highest quality evidence"},
            evidence_refs=["bench_001", "bench_002"],
            configuration_hash="abc123def456",
            status="SELECTED",
        )
        assert d.execution_id == "exec_001"
        assert d.routing_policy_id == policy_id
        assert d.selected_tools == ["web.search", "web.retrieve"]
        assert d.status == "SELECTED"

    def test_status_default_metadata(self):
        assert _col_default(RouteDecisionORM, "status") == "PENDING"
        assert _col_server_default(RouteDecisionORM, "status") == "PENDING"

    def test_candidate_count_default_metadata(self):
        assert _col_default(RouteDecisionORM, "candidate_count") == 0

    def test_foreign_keys(self):
        fks = {
            fk.column.table.name
            for fk in RouteDecisionORM.__table__.c.routing_policy_id.foreign_keys
        }
        assert "routing_policies" in fks

        fks2 = {
            fk.column.table.name
            for fk in RouteDecisionORM.__table__.c.routing_profile_id.foreign_keys
        }
        assert "routing_profiles" in fks2

    def test_indexes_exist(self):
        index_names = {idx.name for idx in RouteDecisionORM.__table__.indexes}
        assert "ix_route_decisions_task" in index_names
        assert "ix_route_decisions_execution" in index_names
        assert "ix_route_decisions_status" in index_names
        assert "ix_route_decisions_created" in index_names

    def test_jsonb_columns(self):
        for col_name in ("selected_tools", "decision_reason", "evidence_refs"):
            assert str(_col(RouteDecisionORM, col_name).type) == "JSONB"


# ════════════════════════════════════════════════════════════════════
# 4. ROUTE CANDIDATES
# ════════════════════════════════════════════════════════════════════


class TestRouteCandidateORM:

    def test_table_name_and_schema(self):
        assert RouteCandidateORM.__tablename__ == "route_candidates"
        assert RouteCandidateORM.__table_args__[-1]["schema"] == "dsrt"

    def test_instantiation(self):
        c = RouteCandidateORM(
            route_decision_id=uuid.uuid4(),
            agent_version_id="agent_v1",
            model_version_id="model_v1",
            world_version_id="world_v1",
            tools=["web.search"],
            eligibility_status="ELIGIBLE",
            capability_fit={"web_research": True, "vision": False},
            constraint_fit={"budget": True, "security": True},
            evidence_summary={"sample_count": 142, "confidence": "HIGH"},
            evaluation_scores={
                "quality": 0.9,
                "reliability": 0.85,
                "latency": 0.7,
                "cost": 0.6,
            },
        )
        assert c.eligibility_status == "ELIGIBLE"
        assert c.capability_fit["web_research"] is True
        assert c.evaluation_scores["quality"] == 0.9

    def test_rejected_candidate(self):
        c = RouteCandidateORM(
            route_decision_id=uuid.uuid4(),
            agent_version_id="a1",
            model_version_id="m1",
            eligibility_status="REJECTED",
            rejection_reason={
                "category": "MISSING_CAPABILITY",
                "detail": "Model does not support vision",
            },
        )
        assert c.eligibility_status == "REJECTED"
        assert c.rejection_reason["category"] == "MISSING_CAPABILITY"

    def test_eligibility_default_metadata(self):
        assert _col_default(RouteCandidateORM, "eligibility_status") == "ELIGIBLE"

    def test_foreign_key_to_decision(self):
        fks = {
            fk.column.table.name
            for fk in RouteCandidateORM.__table__.c.route_decision_id.foreign_keys
        }
        assert "route_decisions" in fks

    def test_indexes_exist(self):
        index_names = {idx.name for idx in RouteCandidateORM.__table__.indexes}
        assert "ix_route_candidates_decision" in index_names
        assert "ix_route_candidates_eligibility" in index_names


# ════════════════════════════════════════════════════════════════════
# 5. ROUTING EVIDENCE
# ════════════════════════════════════════════════════════════════════


class TestRoutingEvidenceORM:

    def test_table_name_and_schema(self):
        assert RoutingEvidenceORM.__tablename__ == "routing_evidence"
        assert RoutingEvidenceORM.__table_args__[-1]["schema"] == "dsrt"

    def test_instantiation(self):
        e = RoutingEvidenceORM(
            source_type="ARENA_BENCHMARK",
            benchmark_id="bench_001",
            benchmark_version="v2",
            model_version="model_v1",
            sample_count=142,
            metrics={"accuracy": 0.92, "latency_p50": 1200},
        )
        assert e.source_type == "ARENA_BENCHMARK"
        assert e.sample_count == 142
        assert e.metrics["accuracy"] == 0.92

    def test_nullable_fields(self):
        e = RoutingEvidenceORM(source_type="PRODUCTION_OBSERVATION")
        assert e.benchmark_id is None
        assert e.agent_version is None
        assert e.model_version is None
        assert e.world_version is None
        assert e.expires_at is None

    def test_sample_count_default_metadata(self):
        assert _col_default(RoutingEvidenceORM, "sample_count") == 0

    def test_indexes_exist(self):
        index_names = {idx.name for idx in RoutingEvidenceORM.__table__.indexes}
        assert "ix_routing_evidence_source" in index_names
        assert "ix_routing_evidence_model" in index_names
        assert "ix_routing_evidence_benchmark" in index_names
        assert "ix_routing_evidence_observed" in index_names


# ════════════════════════════════════════════════════════════════════
# 6. FALLBACK POLICIES
# ════════════════════════════════════════════════════════════════════


class TestFallbackPolicyORM:

    def test_table_name_and_schema(self):
        assert FallbackPolicyORM.__tablename__ == "fallback_policies"
        assert FallbackPolicyORM.__table_args__[-1]["schema"] == "dsrt"

    def test_instantiation(self):
        fp = FallbackPolicyORM(
            name="Default Fallback",
            triggers=["PROVIDER_TIMEOUT", "PROVIDER_RATE_LIMIT"],
            action_type="SWITCH_MODEL",
            candidates=["model_b", "model_c"],
            max_attempts=3,
            backoff_seconds=2.0,
            is_active=True,
        )
        assert fp.name == "Default Fallback"
        assert fp.action_type == "SWITCH_MODEL"
        assert fp.max_attempts == 3
        assert fp.backoff_seconds == 2.0
        assert fp.is_active is True

    def test_defaults_metadata(self):
        assert _col_default(FallbackPolicyORM, "action_type") == "RETRY"
        assert _col_server_default(FallbackPolicyORM, "action_type") == "RETRY"
        assert _col_default(FallbackPolicyORM, "max_attempts") == 3
        assert _col_default(FallbackPolicyORM, "backoff_seconds") == 1.0
        assert _col_default(FallbackPolicyORM, "is_active") is True

    def test_indexes_exist(self):
        index_names = {idx.name for idx in FallbackPolicyORM.__table__.indexes}
        assert "ix_fallback_policies_tenant" in index_names


# ════════════════════════════════════════════════════════════════════
# 7. PROVIDER HEALTH
# ════════════════════════════════════════════════════════════════════


class TestProviderHealthORM:

    def test_table_name_and_schema(self):
        assert ProviderHealthORM.__tablename__ == "provider_health"
        assert ProviderHealthORM.__table_args__[-1]["schema"] == "dsrt"

    def test_instantiation(self):
        now = _utcnow()
        ph = ProviderHealthORM(
            provider_id="openai",
            status="AVAILABLE",
            latency_p50_ms=120.5,
            latency_p99_ms=850.0,
            error_rate=0.002,
            last_success_at=now,
        )
        assert ph.provider_id == "openai"
        assert ph.status == "AVAILABLE"
        assert ph.latency_p50_ms == 120.5
        assert ph.error_rate == 0.002

    def test_status_default_metadata(self):
        assert _col_default(ProviderHealthORM, "status") == "UNKNOWN"
        assert _col_server_default(ProviderHealthORM, "status") == "UNKNOWN"

    def test_has_created_at(self):
        col = _col(ProviderHealthORM, "created_at")
        assert col is not None
        assert col.type.timezone is True

    def test_indexes_exist(self):
        index_names = {idx.name for idx in ProviderHealthORM.__table__.indexes}
        assert "ix_provider_health_provider" in index_names
        assert "ix_provider_health_status" in index_names
        assert "ix_provider_health_expires" in index_names


# ════════════════════════════════════════════════════════════════════
# 8. ROUTE CACHE
# ════════════════════════════════════════════════════════════════════


class TestRouteCacheORM:

    def test_table_name_and_schema(self):
        assert RouteCacheORM.__tablename__ == "route_cache"
        assert RouteCacheORM.__table_args__[-1]["schema"] == "dsrt"

    def test_instantiation(self):
        decision_id = uuid.uuid4()
        expires = _utcnow() + timedelta(hours=1)
        rc = RouteCacheORM(
            cache_key_hash="sha256_abc123",
            requirements_hash="sha256_req456",
            policy_version="1",
            profile_id="builtin_fast",
            provider_health_hash="health789",
            route_decision_id=decision_id,
            expires_at=expires,
        )
        assert rc.cache_key_hash == "sha256_abc123"
        assert rc.route_decision_id == decision_id
        assert rc.expires_at == expires

    def test_unique_constraint(self):
        constraints = [
            c
            for c in RouteCacheORM.__table__.constraints
            if hasattr(c, "name") and c.name == "uq_route_cache_key"
        ]
        assert len(constraints) == 1

    def test_foreign_key_to_decision(self):
        fks = {
            fk.column.table.name
            for fk in RouteCacheORM.__table__.c.route_decision_id.foreign_keys
        }
        assert "route_decisions" in fks

    def test_indexes_exist(self):
        index_names = {idx.name for idx in RouteCacheORM.__table__.indexes}
        assert "ix_route_cache_expires" in index_names


# ════════════════════════════════════════════════════════════════════
# RELATIONSHIP TESTS
# ════════════════════════════════════════════════════════════════════


class TestORMRelationships:

    def test_policy_has_route_decisions_relationship(self):
        rel_names = {r.key for r in RoutingPolicyORM.__mapper__.relationships}
        assert "route_decisions" in rel_names

    def test_profile_has_route_decisions_relationship(self):
        rel_names = {r.key for r in RoutingProfileORM.__mapper__.relationships}
        assert "route_decisions" in rel_names

    def test_decision_has_candidates_relationship(self):
        rel_names = {r.key for r in RouteDecisionORM.__mapper__.relationships}
        assert "candidates" in rel_names

    def test_decision_has_policy_relationship(self):
        rel_names = {r.key for r in RouteDecisionORM.__mapper__.relationships}
        assert "routing_policy" in rel_names

    def test_decision_has_profile_relationship(self):
        rel_names = {r.key for r in RouteDecisionORM.__mapper__.relationships}
        assert "routing_profile" in rel_names

    def test_decision_has_cache_relationship(self):
        rel_names = {r.key for r in RouteDecisionORM.__mapper__.relationships}
        assert "cache_entries" in rel_names

    def test_candidate_has_decision_relationship(self):
        rel_names = {r.key for r in RouteCandidateORM.__mapper__.relationships}
        assert "route_decision" in rel_names

    def test_cache_has_decision_relationship(self):
        rel_names = {r.key for r in RouteCacheORM.__mapper__.relationships}
        assert "route_decision" in rel_names


# ════════════════════════════════════════════════════════════════════
# COLUMN TYPE VALIDATION
# ════════════════════════════════════════════════════════════════════


class TestColumnTypes:

    def test_all_ids_are_uuid(self):
        for model in (
            RoutingPolicyORM,
            RoutingProfileORM,
            RouteDecisionORM,
            RouteCandidateORM,
            RoutingEvidenceORM,
            FallbackPolicyORM,
            ProviderHealthORM,
            RouteCacheORM,
        ):
            col = _col(model, "id")
            assert str(col.type) == "UUID", f"{model.__name__}.id is not UUID"

    def test_all_created_at_are_tz_aware(self):
        for model in (
            RoutingPolicyORM,
            RoutingProfileORM,
            RouteDecisionORM,
            RouteCandidateORM,
            RoutingEvidenceORM,
            FallbackPolicyORM,
            ProviderHealthORM,
            RouteCacheORM,
        ):
            col = _col(model, "created_at")
            assert col.type.timezone is True, (
                f"{model.__name__}.created_at is not timezone-aware"
            )

    def test_jsonb_columns_in_decision(self):
        for col_name in ("selected_tools", "decision_reason", "evidence_refs"):
            assert str(_col(RouteDecisionORM, col_name).type) == "JSONB"

    def test_jsonb_columns_in_candidate(self):
        for col_name in (
            "tools",
            "rejection_reason",
            "capability_fit",
            "constraint_fit",
            "evidence_summary",
            "evaluation_scores",
        ):
            assert str(_col(RouteCandidateORM, col_name).type) == "JSONB"

    def test_jsonb_columns_in_evidence(self):
        assert str(_col(RoutingEvidenceORM, "metrics").type) == "JSONB"

    def test_jsonb_columns_in_fallback(self):
        for col_name in ("triggers", "candidates"):
            assert str(_col(FallbackPolicyORM, col_name).type) == "JSONB"

    def test_float_columns_in_health(self):
        for col_name in ("latency_p50_ms", "latency_p99_ms", "error_rate"):
            col = _col(ProviderHealthORM, col_name)
            assert "FLOAT" in str(col.type).upper()

    def test_string_columns_in_cache(self):
        for col_name in (
            "cache_key_hash",
            "requirements_hash",
            "policy_version",
            "provider_health_hash",
        ):
            col = _col(RouteCacheORM, col_name)
            assert "VARCHAR" in str(col.type).upper()


# ════════════════════════════════════════════════════════════════════
# TABLE COUNT VALIDATION
# ════════════════════════════════════════════════════════════════════


class TestTableCount:

    def test_eight_c9_tables(self):
        c9_models = [
            RoutingPolicyORM,
            RoutingProfileORM,
            RouteDecisionORM,
            RouteCandidateORM,
            RoutingEvidenceORM,
            FallbackPolicyORM,
            ProviderHealthORM,
            RouteCacheORM,
        ]
        assert len(c9_models) == 8

    def test_all_in_dsrt_schema(self):
        for model in (
            RoutingPolicyORM,
            RoutingProfileORM,
            RouteDecisionORM,
            RouteCandidateORM,
            RoutingEvidenceORM,
            FallbackPolicyORM,
            ProviderHealthORM,
            RouteCacheORM,
        ):
            schema = model.__table_args__[-1].get("schema")
            assert schema == "dsrt", f"{model.__name__} is not in dsrt schema"