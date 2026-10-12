"""Integration tests for Usage Meter database operations (C2.10)."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from core.models.registry.registry import ModelRegistry
from core.models.usage.meter import UsageMeter
from core.repositories import (
    AgentRepository,
    CapabilityRepository,
    ExecutionRepository,
    OrganizationRepository,
    ProviderRepository,
    TaskRepository,
    UsageRepository,
    UserRepository,
)
from core.storage.database import db_manager
from schemas.domain import FinishReason, ModelResponse, Usage
from schemas.domain.enums import ProviderType


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class TestUsageMeterIntegration:
    async def test_usage_meter_records_and_aggregates(self):
        suffix = uuid.uuid4().hex[:8]

        async with db_manager.session() as session:
            # 1. Seed Organization & User
            org_repo = OrganizationRepository(session)
            user_repo = UserRepository(session)
            org = await org_repo.create(name=f"Org {suffix}", slug=f"org-{suffix}")
            user = await user_repo.create(
                email=f"user-{suffix}@example.com",
                display_name="User",
                password_hash="hash",
            )
            await org_repo.add_member(organization_id=org.id, user_id=user.id, role="owner")

            # 2. Seed Capability, Agent & Version
            cap_repo = CapabilityRepository(session)
            agent_repo = AgentRepository(session)
            cap = await cap_repo.create(
                slug=f"cap_{suffix}", name="Cap", description="D", version="1.0.0"
            )
            agent = await agent_repo.create_agent(
                slug=f"agent_{suffix}",
                name="Agent",
                description="D",
                category="test",
                publisher="dsrt",
            )
            agent_ver = await agent_repo.create_agent_version(
                agent_id=agent.id,
                version="1.0.0",
                contract_version="1.0",
                manifest={"identity": {"id": agent.slug, "version": "1.0.0"}},
                package_reference="pkg",
                configuration={},
                requirements={},
                permissions={},
            )
            await agent_repo.link_capability(agent_ver.id, cap.id)

            # 3. Seed Task & Execution (creates real FK parent rows)
            task_repo = TaskRepository(session)
            exe_repo = ExecutionRepository(session)
            task = await task_repo.create(
                organization_id=org.id,
                user_id=user.id,
                agent_slug=agent.slug,
                objective="Usage test",
            )
            execution = await exe_repo.create(
                task_id=task.id,
                organization_id=org.id,
                core_version="1.0.0",
                agent_version_id=agent_ver.id,
                contract_version="1.0",
                configuration_hash="0" * 64,
            )

            # 4. Seed Provider & Model
            prov_repo = ProviderRepository(session)
            prv = await prov_repo.create_provider(
                slug=f"prov_{suffix}", name="P", provider_type=ProviderType.CLOUD.value
            )
            mdl = await prov_repo.create_model(
                provider_id=prv.id,
                slug=f"mdl_{suffix}",
                name="M",
                model_identifier="m-1",
                version="1.0",
                capabilities={
                    "capabilities": {},
                    "context_config": {"max_input_tokens": 10, "max_output_tokens": 10},
                    "pricing_config": {
                        "input_cost_per_m": "10.0",
                        "output_cost_per_m": "20.0"
                    },
                },
            )

            # 5. Setup Usage Meter
            usage_repo = UsageRepository(session)
            model_reg = ModelRegistry(prov_repo)
            meter = UsageMeter(usage_repo, model_reg)

            # 6. Create ModelResponses with usage
            resp1 = ModelResponse(
                request_id="req_1",
                model_id=mdl.id,
                provider_id=prv.id,
                model_identifier="m-1",
                finish_reason=FinishReason.COMPLETED,
                usage=Usage(input_tokens=100000, output_tokens=50000),
                latency_ms=100,
                created_at=datetime.now(timezone.utc),
            )

            resp2 = ModelResponse(
                request_id="req_2",
                model_id=mdl.id,
                provider_id=prv.id,
                model_identifier="m-1",
                finish_reason=FinishReason.COMPLETED,
                usage=Usage(input_tokens=200000, output_tokens=100000),
                latency_ms=100,
                created_at=datetime.now(timezone.utc),
            )

            # 7. Record usage against real execution.id
            await meter.record_model_response(org.id, execution.id, resp1)
            await meter.record_model_response(org.id, execution.id, resp2)

            # 8. Verify Aggregation
            agg = await meter.get_execution_usage(execution.id)

            assert agg["input_tokens"] == 300000
            assert agg["output_tokens"] == 150000

            # Expected Cost:
            # Input: (300k / 1M) * $10 = $3.00
            # Output: (150k / 1M) * $20 = $3.00
            # Total: $6.00
            assert agg["estimated_cost_usd"] == Decimal("6.000000")