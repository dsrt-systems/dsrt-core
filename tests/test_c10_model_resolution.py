"""
C10.6 — Model Resolution & Profile Registry tests.

Covers:
1. ModelFingerprint — determinism, hashing, matching, unknown fields
2. ModelResolver — success, missing connection, unreachable, capability mismatch
3. ProfileRegistry — shared/connection/execution profiles
4. Evidence reuse flagging (critical rule)
5. TieredProfilingOrchestrator — planning + execution
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from core.execution.models.fingerprint import (
    ModelFingerprint,
    ModelFingerprinter,
    FingerprintField,
)
from core.execution.models.resolver import (
    CapabilityMismatchError,
    ConnectionNotFoundError,
    ConnectionSource,
    ConnectionUnavailableError,
    ModelResolver,
    ResolvedModelConnection,
    ResolutionError,
)
from core.execution.models.profiles import (
    ConnectionProfile,
    ConnectionProfileService,
    ExecutionProfileService,
    InMemoryProfileStore,
    ProfileRegistry,
    SharedModelProfile,
    SharedProfileService,
)
from core.execution.models.profiling import (
    ProfilingDecision,
    ProfilingRequest,
    ProfilingResult,
    ProfilingTier,
    TieredProfilingOrchestrator,
)


# =====================================================================
# Helpers
# =====================================================================

_DEFAULT_CONNECTION: dict = {
    "provider": "openai",
    "display_name": "OpenAI (prod)",
    "endpoint": "https://api.openai.com/v1",
    "source": "USER_BYOK",
    "rate_limit_rpm": 500,
    "rate_limit_tpm": 300000,
}

_DEFAULT_METADATA: dict = {
    "provider": "openai",
    "snapshot": "2024-05-13",
    "endpoint": "https://api.openai.com/v1",
    "capabilities": ["chat", "tool_use", "streaming"],
    "supports_streaming": True,
    "supports_tool_use": True,
    "context_window_tokens": 128000,
    "max_output_tokens": 4096,
    "inference_configuration": {},
    "tool_capabilities": ["function_calling"],
}

_DEFAULT_VERIFY: dict = {
    "reachable": True,
    "latency_ms": 42,
    "error": None,
}


def _make_gateway(
    *,
    connection: dict | None = None,
    verify: dict | None = None,
    metadata: dict | None = None,
    connection_missing: bool = False,
    use_default_connection: bool = True,
    use_default_metadata: bool = True,
    use_default_verify: bool = True,
) -> AsyncMock:
    """
    Build a mock ModelGatewayAdapter.

    Empty dicts are honored as empty (not replaced by defaults).
    Pass connection_missing=True to simulate a missing connection.
    To force truly empty metadata while keeping other defaults, pass
    metadata={} with use_default_metadata left as default path via
    explicit metadata argument (see below).
    """
    gw = AsyncMock()

    if connection_missing:
        conn_value = None
    elif connection is not None:
        # Caller supplied an explicit connection dict (even if empty).
        conn_value = connection
    elif use_default_connection:
        conn_value = dict(_DEFAULT_CONNECTION)
    else:
        conn_value = None

    if verify is not None:
        verify_value = verify
    elif use_default_verify:
        verify_value = dict(_DEFAULT_VERIFY)
    else:
        verify_value = {"reachable": False, "latency_ms": None, "error": None}

    if metadata is not None:
        # Caller supplied explicit metadata (even if empty {}).
        metadata_value = metadata
    elif use_default_metadata:
        metadata_value = dict(_DEFAULT_METADATA)
    else:
        metadata_value = {}

    gw.get_connection = AsyncMock(return_value=conn_value)
    gw.verify_connection = AsyncMock(return_value=verify_value)
    gw.get_model_metadata = AsyncMock(return_value=metadata_value)
    return gw


# =====================================================================
# 1. ModelFingerprint
# =====================================================================

class TestModelFingerprint:
    def test_basic_fingerprint(self):
        fp = ModelFingerprinter().fingerprint(
            provider="openai",
            model_id="gpt-4o",
            model_snapshot="2024-05-13",
            inference_configuration={"temperature": 0.7},
        )
        assert fp.provider == "openai"
        assert fp.model_id == "gpt-4o"
        assert fp.fingerprint_hash != ""
        assert len(fp.fingerprint_hash) == 64

    def test_identical_inputs_identical_hash(self):
        f = ModelFingerprinter()
        fp1 = f.fingerprint(
            provider="openai", model_id="gpt-4o",
            model_snapshot="2024-05-13",
            inference_configuration={"temperature": 0.7},
        )
        fp2 = f.fingerprint(
            provider="openai", model_id="gpt-4o",
            model_snapshot="2024-05-13",
            inference_configuration={"temperature": 0.7},
        )
        assert fp1.matches(fp2)
        assert fp1.fingerprint_hash == fp2.fingerprint_hash

    def test_different_snapshot_different_hash(self):
        f = ModelFingerprinter()
        fp1 = f.fingerprint(
            provider="openai", model_id="gpt-4o",
            model_snapshot="2024-05-13",
        )
        fp2 = f.fingerprint(
            provider="openai", model_id="gpt-4o",
            model_snapshot="2024-08-06",
        )
        assert not fp1.matches(fp2)

    def test_different_inference_config_different_hash(self):
        f = ModelFingerprinter()
        fp1 = f.fingerprint(
            provider="openai", model_id="gpt-4o",
            inference_configuration={"temperature": 0.0},
        )
        fp2 = f.fingerprint(
            provider="openai", model_id="gpt-4o",
            inference_configuration={"temperature": 0.7},
        )
        assert not fp1.matches(fp2)

    def test_unknown_fields_recorded(self):
        fp = ModelFingerprinter().fingerprint(
            provider="openai", model_id="gpt-4o",
        )
        assert FingerprintField.MODEL_SNAPSHOT.value in fp.unknown_fields
        assert FingerprintField.QUANTIZATION.value in fp.unknown_fields
        assert FingerprintField.SERVING_HARDWARE.value in fp.unknown_fields
        assert FingerprintField.ENDPOINT_IDENTITY.value in fp.unknown_fields

    def test_requires_provider_and_model(self):
        f = ModelFingerprinter()
        with pytest.raises(ValueError, match="provider"):
            f.fingerprint(provider="", model_id="gpt-4o")
        with pytest.raises(ValueError, match="model_id"):
            f.fingerprint(provider="openai", model_id="")

    def test_from_provider_response(self):
        fp = ModelFingerprinter().from_provider_response(
            provider="openai",
            model_id="gpt-4o",
            provider_metadata={
                "snapshot": "2024-05-13",
                "endpoint": "https://api.openai.com/v1",
                "quantization": "fp16",
                "serving_hardware": "H100",
                "tool_capabilities": ["function_calling"],
                "inference_configuration": {"temperature": 0.7},
            },
        )
        assert fp.model_snapshot == "2024-05-13"
        assert fp.quantization == "fp16"
        assert fp.serving_hardware == "H100"
        assert fp.tool_capabilities == ["function_calling"]
        assert fp.unknown_fields == []

    def test_display_name(self):
        fp = ModelFingerprinter().fingerprint(
            provider="openai", model_id="gpt-4o",
            model_snapshot="2024-05-13",
        )
        assert fp.display_name() == "openai/gpt-4o/2024-05-13"

    def test_tool_capability_order_does_not_affect_hash(self):
        f = ModelFingerprinter()
        fp1 = f.fingerprint(
            provider="openai", model_id="gpt-4o",
            tool_capabilities=["a", "b", "c"],
        )
        fp2 = f.fingerprint(
            provider="openai", model_id="gpt-4o",
            tool_capabilities=["c", "a", "b"],
        )
        assert fp1.matches(fp2)


# =====================================================================
# 2. ModelResolver
# =====================================================================

class TestModelResolver:
    @pytest.mark.asyncio
    async def test_successful_resolution(self):
        gw = _make_gateway()
        resolver = ModelResolver(gateway=gw)

        resolved = await resolver.resolve(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
        )

        assert isinstance(resolved, ResolvedModelConnection)
        assert resolved.fingerprint.provider == "openai"
        assert resolved.fingerprint.model_snapshot == "2024-05-13"
        assert resolved.connection_source == ConnectionSource.USER_BYOK
        assert resolved.reachable is True
        assert resolved.reachability_latency_ms == 42
        assert resolved.supports_streaming is True
        assert resolved.supports_tool_use is True
        assert resolved.context_window_tokens == 128000

    @pytest.mark.asyncio
    async def test_missing_connection(self):
        gw = _make_gateway(connection_missing=True)
        resolver = ModelResolver(gateway=gw)

        with pytest.raises(ConnectionNotFoundError):
            await resolver.resolve(
                workspace_id="ws-1",
                connection_id="missing",
                model_id="gpt-4o",
            )

    @pytest.mark.asyncio
    async def test_unreachable_connection(self):
        gw = _make_gateway(
            verify={
                "reachable": False,
                "latency_ms": None,
                "error": "connection timeout",
            },
        )
        resolver = ModelResolver(gateway=gw)

        with pytest.raises(ConnectionUnavailableError):
            await resolver.resolve(
                workspace_id="ws-1",
                connection_id="conn-1",
                model_id="gpt-4o",
            )

    @pytest.mark.asyncio
    async def test_capability_mismatch(self):
        gw = _make_gateway(
            metadata={
                "provider": "openai",
                "capabilities": ["chat"],  # missing tool_use
                "snapshot": "2024-05-13",
            },
        )
        resolver = ModelResolver(gateway=gw)

        with pytest.raises(CapabilityMismatchError, match="tool_use"):
            await resolver.resolve(
                workspace_id="ws-1",
                connection_id="conn-1",
                model_id="gpt-4o",
                required_capabilities=["chat", "tool_use"],
            )

    @pytest.mark.asyncio
    async def test_skip_reachability_check(self):
        gw = _make_gateway()
        resolver = ModelResolver(gateway=gw)

        resolved = await resolver.resolve(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
            verify_reachable=False,
        )
        assert resolved.reachable is True  # default when skipped
        gw.verify_connection.assert_not_called()

    @pytest.mark.asyncio
    async def test_unknown_source_warns_and_defaults(self):
        gw = _make_gateway(
            connection={
                "provider": "openai",
                "source": "SOMETHING_ELSE",
            },
        )
        resolver = ModelResolver(gateway=gw)

        resolved = await resolver.resolve(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
        )
        assert resolved.connection_source == ConnectionSource.USER_BYOK
        assert any("Unknown connection source" in w for w in resolved.warnings)

    @pytest.mark.asyncio
    async def test_missing_provider_raises(self):
        gw = _make_gateway(
            connection={"display_name": "No Provider"},
            metadata={},
        )
        resolver = ModelResolver(gateway=gw)

        with pytest.raises(ResolutionError, match="provider not identified"):
            await resolver.resolve(
                workspace_id="ws-1",
                connection_id="conn-1",
                model_id="gpt-4o",
            )

    @pytest.mark.asyncio
    async def test_metadata_fetch_failure_recorded_as_warning(self):
        gw = _make_gateway()
        gw.get_model_metadata = AsyncMock(side_effect=RuntimeError("API down"))

        resolver = ModelResolver(gateway=gw)
        resolved = await resolver.resolve(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
        )
        assert any("Model metadata unavailable" in w for w in resolved.warnings)
        assert resolved.fingerprint.model_snapshot is None


# =====================================================================
# 3. Profile services
# =====================================================================

class TestProfileServices:
    @pytest.mark.asyncio
    async def test_shared_profile_get_or_create(self):
        store = InMemoryProfileStore()
        service = SharedProfileService(store)
        fp = ModelFingerprinter().fingerprint(
            provider="openai", model_id="gpt-4o",
            model_snapshot="2024-05-13",
        )

        p1, created1 = await service.get_or_create(fp)
        assert created1 is True
        assert p1.fingerprint_hash == fp.fingerprint_hash

        p2, created2 = await service.get_or_create(fp)
        assert created2 is False
        assert p2.profile_id == p1.profile_id

    @pytest.mark.asyncio
    async def test_record_benchmark_evidence(self):
        store = InMemoryProfileStore()
        service = SharedProfileService(store)
        fp = ModelFingerprinter().fingerprint(
            provider="openai", model_id="gpt-4o",
        )
        await service.get_or_create(fp)

        p = await service.record_benchmark_evidence(
            fingerprint_hash=fp.fingerprint_hash,
            evidence={"benchmark": "mmlu", "score": 0.87},
            source_connection_id="conn-A",
        )
        assert p.evidence_count == 1
        assert p.source_count == 1

        p = await service.record_benchmark_evidence(
            fingerprint_hash=fp.fingerprint_hash,
            evidence={"benchmark": "gsm8k", "score": 0.92},
            source_connection_id="conn-B",
        )
        assert p.evidence_count == 2
        assert p.source_count == 2

    @pytest.mark.asyncio
    async def test_record_evidence_requires_existing_profile(self):
        store = InMemoryProfileStore()
        service = SharedProfileService(store)
        with pytest.raises(ValueError, match="No shared profile"):
            await service.record_benchmark_evidence(
                fingerprint_hash="nope",
                evidence={},
                source_connection_id="c",
            )

    @pytest.mark.asyncio
    async def test_connection_profile_lifecycle(self):
        store = InMemoryProfileStore()
        service = ConnectionProfileService(store)

        p = await service.register(
            workspace_id="ws-1",
            connection_id="conn-1",
            provider="openai",
            display_name="OpenAI prod",
            rate_limit_rpm=500,
        )
        assert p.is_active
        assert p.verified_at is not None

        fetched = await service.get(workspace_id="ws-1", connection_id="conn-1")
        assert fetched is not None
        assert fetched.profile_id == p.profile_id

        revoked = await service.revoke(
            workspace_id="ws-1", connection_id="conn-1",
        )
        assert revoked.is_active is False
        assert revoked.revoked_at is not None

    @pytest.mark.asyncio
    async def test_revoke_missing_connection_raises(self):
        store = InMemoryProfileStore()
        service = ConnectionProfileService(store)
        with pytest.raises(ValueError, match="not found"):
            await service.revoke(workspace_id="ws", connection_id="missing")

    @pytest.mark.asyncio
    async def test_execution_profile_aggregation(self):
        store = InMemoryProfileStore()
        service = ExecutionProfileService(store)

        for i in range(3):
            await service.record_execution(
                workspace_id="ws-1",
                connection_id="conn-1",
                fingerprint_hash="fphash",
                succeeded=True,
                input_tokens=100,
                output_tokens=50,
                cost_usd=0.01,
                duration_ms=100 + i * 50,  # 100, 150, 200
            )

        p = await service.get(
            workspace_id="ws-1",
            connection_id="conn-1",
            fingerprint_hash="fphash",
        )
        assert p is not None
        assert p.total_executions == 3
        assert p.successful_executions == 3
        assert p.total_input_tokens == 300
        assert p.total_cost_usd == pytest.approx(0.03)
        assert p.min_latency_ms == 100
        assert p.max_latency_ms == 200
        assert p.avg_latency_ms == pytest.approx(150.0)
        assert p.success_rate == 1.0

    @pytest.mark.asyncio
    async def test_execution_profile_tracks_errors(self):
        store = InMemoryProfileStore()
        service = ExecutionProfileService(store)

        await service.record_execution(
            workspace_id="ws-1", connection_id="c", fingerprint_hash="fp",
            succeeded=True, input_tokens=10, output_tokens=5,
            cost_usd=0.001, duration_ms=50,
        )
        await service.record_execution(
            workspace_id="ws-1", connection_id="c", fingerprint_hash="fp",
            succeeded=False, input_tokens=10, output_tokens=0,
            cost_usd=0.0005, duration_ms=100, error_type="RateLimitError",
        )
        await service.record_execution(
            workspace_id="ws-1", connection_id="c", fingerprint_hash="fp",
            succeeded=False, input_tokens=10, output_tokens=0,
            cost_usd=0.0005, duration_ms=100, error_type="RateLimitError",
        )

        p = await service.get(
            workspace_id="ws-1", connection_id="c", fingerprint_hash="fp",
        )
        assert p.failed_executions == 2
        assert p.error_counts["RateLimitError"] == 2
        assert p.success_rate == pytest.approx(1 / 3)


# =====================================================================
# 4. Evidence reuse flagging (critical rule)
# =====================================================================

class TestEvidenceReuseFlagging:
    @pytest.mark.asyncio
    async def test_fresh_vs_reused_separation(self):
        registry = ProfileRegistry()
        fp = ModelFingerprinter().fingerprint(
            provider="openai", model_id="gpt-4o",
        )

        await registry.shared.get_or_create(fp)
        await registry.shared.record_benchmark_evidence(
            fingerprint_hash=fp.fingerprint_hash,
            evidence={"benchmark": "mmlu", "score": 0.87},
            source_connection_id="conn-other-user",  # someone else's connection
        )
        await registry.shared.record_benchmark_evidence(
            fingerprint_hash=fp.fingerprint_hash,
            evidence={"benchmark": "gsm8k", "score": 0.92},
            source_connection_id="conn-mine",  # user's own connection
        )

        evidence = await registry.get_evidence_for_user(
            workspace_id="ws-1",
            connection_id="conn-mine",
            fingerprint_hash=fp.fingerprint_hash,
        )

        assert len(evidence["fresh_evidence"]) == 1
        assert len(evidence["reused_evidence"]) == 1
        assert evidence["fresh_evidence"][0]["benchmark"] == "gsm8k"
        assert evidence["fresh_evidence"][0]["is_reused_evidence"] is False
        assert evidence["reused_evidence"][0]["benchmark"] == "mmlu"
        assert evidence["reused_evidence"][0]["is_reused_evidence"] is True

    @pytest.mark.asyncio
    async def test_no_evidence_returns_empty_lists(self):
        registry = ProfileRegistry()
        evidence = await registry.get_evidence_for_user(
            workspace_id="ws-1",
            connection_id="conn-1",
            fingerprint_hash="nonexistent",
        )
        assert evidence["fresh_evidence"] == []
        assert evidence["reused_evidence"] == []
        assert evidence["observed_execution_profile"] is None


# =====================================================================
# 5. TieredProfilingOrchestrator
# =====================================================================

class TestTieredProfilingOrchestrator:
    def _make_orchestrator(self, gateway: AsyncMock | None = None):
        gw = gateway or _make_gateway()
        resolver = ModelResolver(gateway=gw)
        registry = ProfileRegistry()
        return (
            TieredProfilingOrchestrator(resolver=resolver, registry=registry),
            gw,
        )

    def test_plan_tier_0_always_planned(self):
        orch, _ = self._make_orchestrator()
        request = ProfilingRequest(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
            requested_tier=ProfilingTier.IDENTIFY,
        )
        decision = orch.plan(request)
        assert ProfilingTier.IDENTIFY.value in decision.planned_tiers
        assert decision.requires_user_authorization == []

    def test_plan_tier_2_needs_authorization(self):
        orch, _ = self._make_orchestrator()
        request = ProfilingRequest(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
            requested_tier=ProfilingTier.DOMAIN_PROBE,
            user_authorized_tiers=[],
        )
        decision = orch.plan(request)
        assert ProfilingTier.IDENTIFY.value in decision.planned_tiers
        assert ProfilingTier.VERIFY.value in decision.planned_tiers
        assert ProfilingTier.DOMAIN_PROBE.value in decision.skipped_tiers
        assert ProfilingTier.DOMAIN_PROBE.value in decision.requires_user_authorization

    def test_plan_authorized_tier_2_included(self):
        orch, _ = self._make_orchestrator()
        request = ProfilingRequest(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
            requested_tier=ProfilingTier.DOMAIN_PROBE,
            user_authorized_tiers=[ProfilingTier.DOMAIN_PROBE.value],
        )
        decision = orch.plan(request)
        assert ProfilingTier.DOMAIN_PROBE.value in decision.planned_tiers

    @pytest.mark.asyncio
    async def test_execute_tier_0_only(self):
        orch, _ = self._make_orchestrator()
        request = ProfilingRequest(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
            requested_tier=ProfilingTier.IDENTIFY,
        )
        result = await orch.execute(request)
        assert result.highest_tier_executed == ProfilingTier.IDENTIFY.value
        assert result.fingerprint is not None
        assert result.fingerprint.provider == "openai"
        assert result.reused_shared_profile is False
        assert result.total_cost_usd == 0.0

    @pytest.mark.asyncio
    async def test_execute_tier_0_reuses_shared(self):
        orch, _ = self._make_orchestrator()
        request = ProfilingRequest(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
            requested_tier=ProfilingTier.IDENTIFY,
        )
        first = await orch.execute(request)
        assert first.reused_shared_profile is False

        second = await orch.execute(request)
        assert second.reused_shared_profile is True

    @pytest.mark.asyncio
    async def test_execute_through_tier_1(self):
        orch, gw = self._make_orchestrator()
        request = ProfilingRequest(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
            requested_tier=ProfilingTier.VERIFY,
        )
        result = await orch.execute(request)
        assert result.highest_tier_executed == ProfilingTier.VERIFY.value
        verify_result = next(
            r for r in result.tier_results
            if r.tier == ProfilingTier.VERIFY.value and r.status == "EXECUTED"
        )
        assert verify_result.details["reachable"] is True
        assert verify_result.details["supports_tool_use"] is True

    @pytest.mark.asyncio
    async def test_execute_unauthorized_tier_marked(self):
        orch, _ = self._make_orchestrator()
        request = ProfilingRequest(
            workspace_id="ws-1",
            connection_id="conn-1",
            model_id="gpt-4o",
            requested_tier=ProfilingTier.FRESH_EXPERIMENT,
            user_authorized_tiers=[],  # nothing authorized above tier 1
        )
        result = await orch.execute(request)

        unauthorized = [
            r for r in result.tier_results if r.status == "UNAUTHORIZED"
        ]
        assert len(unauthorized) >= 1
        assert any(
            r.tier == ProfilingTier.FRESH_EXPERIMENT.value
            for r in unauthorized
        )
        assert result.highest_tier_executed == ProfilingTier.VERIFY.value

    @pytest.mark.asyncio
    async def test_tier_failure_stops_execution(self):
        gw = _make_gateway(connection_missing=True)
        orch, _ = self._make_orchestrator(gateway=gw)
        request = ProfilingRequest(
            workspace_id="ws-1",
            connection_id="missing",
            model_id="gpt-4o",
            requested_tier=ProfilingTier.VERIFY,
        )
        result = await orch.execute(request)

        failed = [r for r in result.tier_results if r.status == "FAILED"]
        assert len(failed) >= 1
        assert result.highest_tier_executed == -1