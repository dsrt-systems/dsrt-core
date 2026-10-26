"""
Unit test suite for Phase C11.10 Observability & Explainability.
"""

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB

from core.optimization.controller.master_controller import MasterOptimizationController
from core.optimization.events.publisher import (
    OptimizationCompletedEvent,
    OptimizationEventPublisher,
)
from core.optimization.explainability.explainer import DecisionExplainer
from core.optimization.reconciliation.reconciler import PerformanceReconciler
from core.storage.database import Base
from core.storage.models.optimization_c11_governance import (
    FallbackStateModel,
    OptimizationDecisionModel,
    OptimizationPolicyModel,
    OptimizationSnapshotModel,
)
from core.storage.models.optimization_c11_observability import ReconciliationReportModel
from schemas.domain.governance import DecisionType, OptimizationRequest
from schemas.domain.observability import ExecutionActuals


@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"dsrt": None})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_decision_explainer(db_session):
    controller = MasterOptimizationController(db_session)
    request = OptimizationRequest(
        request_id="req_explain_1001",
        tenant_id="tenant_alpha",
        prompt="Build microservice with high performance",
        max_budget_usd=1.00,
    )
    plan = controller.optimize(request)

    explainer = DecisionExplainer(db_session)
    explanation = explainer.explain_request("req_explain_1001", "tenant_alpha")

    assert explanation is not None
    assert explanation.request_id == "req_explain_1001"
    assert len(explanation.decisions) >= 3
    assert explanation.cost_breakdown_usd["total_cost_usd"] > 0.0
    assert "Model selected" in explanation.model_selection_reasoning


def test_performance_reconciler(db_session):
    controller = MasterOptimizationController(db_session)
    request = OptimizationRequest(
        request_id="req_recon_2002",
        tenant_id="tenant_alpha",
        prompt="Fix database deadlock bug",
        max_budget_usd=0.50,
    )
    plan = controller.optimize(request)

    actuals = ExecutionActuals(
        request_id="req_recon_2002",
        tenant_id="tenant_alpha",
        actual_cost_usd=0.04,
        actual_latency_ms=1300.0,
        actual_quality_score=0.90,
    )

    reconciler = PerformanceReconciler(db_session)
    report = reconciler.reconcile(actuals)

    assert report.request_id == "req_recon_2002"
    assert report.actual_cost_usd == 0.04
    assert isinstance(report.cost_error_pct, float)


def test_event_publisher_dispatch():
    OptimizationEventPublisher.clear_subscribers()
    received_events = []

    def handle_completed(event):
        received_events.append(event)

    OptimizationEventPublisher.subscribe("optimization.completed", handle_completed)

    pub = OptimizationEventPublisher()
    pub.publish(
        OptimizationCompletedEvent(
            request_id="req_evt_3003",
            tenant_id="tenant_beta",
            plan_id="plan_3003",
            estimated_cost_usd=0.05,
        )
    )

    assert len(received_events) == 1
    assert received_events[0].request_id == "req_evt_3003"


async def test_api_endpoints_integration(db_session):
    from api.v1.optimization import router
    from fastapi import FastAPI
    from core.storage.database import get_db

    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. Optimize
        resp = await client.post(
            "/api/v1/optimization/optimize",
            json={
                "request_id": "req_api_4004",
                "tenant_id": "tenant_gamma",
                "prompt": "Optimize SQL query index",
                "max_budget_usd": 0.50,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["request_id"] == "req_api_4004"

        # 2. Decision explanation
        resp_exp = await client.get(
            "/api/v1/optimization/decisions/req_api_4004?tenant_id=tenant_gamma"
        )
        assert resp_exp.status_code == 200
        exp_data = resp_exp.json()
        assert exp_data["request_id"] == "req_api_4004"

        # 3. Metrics
        resp_met = await client.get("/api/v1/optimization/metrics")
        assert resp_met.status_code == 200
        met_data = resp_met.json()
        assert met_data["total_optimizations"] >= 1
