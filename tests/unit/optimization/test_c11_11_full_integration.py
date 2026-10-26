"""
C11.11 Integration & Full Definition of Done Validation Tests.
"""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.pool import StaticPool

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(type_, compiler, **kw):
    return "TEXT"

from core.storage.database import Base
from core.storage.models.optimization_c11 import (
    TaskProfileModel,
    OptimizationRequestModel,
    PerformanceEvidenceModel,
    ModelPerformanceProfileModel,
    StrategyDefinitionModel,
    OptimizationPlanModel,
    AdaptationEventModel,
    VerificationPipelineModel,
    StrategyArmStateModel,
)
from core.storage.models.optimization_c11_governance import (
    OptimizationPolicyModel,
    OptimizationDecisionModel,
    FallbackStateModel,
)
from core.storage.models.optimization_c11_observability import ReconciliationReportModel

from core.optimization.integration.c9_adapter import C9ExecutionAdapter
from core.optimization.integration.c10_adapter import C10GovernanceAdapter
from core.optimization.integration.c8_benchmark_ingester import C8BenchmarkIngester
from core.optimization.workers.optimization_workers import OptimizationWorkerManager
from core.optimization.approval.workflow import ApprovalWorkflowManager, ApprovalStatus
from tests.benchmarks.c9_vs_c11_comparison import C9VsC11ComparativeBenchmark


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


def test_c9_adapter_execution_flow(db_session):
    adapter = C9ExecutionAdapter(db_session)
    c9_request = {
        "request_id": "req_c9_001",
        "tenant_id": "tenant_test",
        "prompt": "Write a Python script to filter JSON logs.",
        "max_cost_usd": 0.10,
    }
    directives = adapter.prepare_execution_directives(c9_request)
    assert directives["task_id"] == "task_req_c9_001"
    assert directives["selected_model"] in ["claude-3-5-sonnet", "gpt-4o", "gpt-4o-mini"]
    assert "verification_pipeline" in directives


def test_c10_governance_cost_ledger_adapter(db_session):
    adapter = C10GovernanceAdapter(db_session)
    authorized = adapter.check_tenant_budget_authorization("tenant_test", 0.05)
    assert authorized is True

    record = adapter.record_actual_execution_cost("tenant_test", "req_001", 0.042, "gpt-4o-mini", "success")
    assert record["cost_usd"] == 0.042
    assert record["ledger_entry_type"] == "c11_optimized_execution"


def test_c8_benchmark_ingester(db_session):
    ingester = C8BenchmarkIngester(db_session)
    records = [
        {"task_classification": "coding", "model_id": "gpt-4o", "cost_usd": 0.02, "quality_score": 0.95, "is_success": True},
        {"task_classification": "coding", "model_id": "claude-3-5-sonnet", "cost_usd": 0.03, "quality_score": 0.98, "is_success": True},
    ]
    count = ingester.ingest_benchmark_results(records)
    assert count == 2


def test_background_workers(db_session):
    worker_mgr = OptimizationWorkerManager(db_session)
    res_prof = worker_mgr.run_profile_aggregation_worker()
    res_learn = worker_mgr.run_learning_worker()

    assert res_prof["status"] == "success"
    assert res_learn["status"] == "success"


def test_approval_workflow():
    mgr = ApprovalWorkflowManager()
    req = mgr.create_request(
        tenant_id="tenant_admin",
        change_type="fixed_model_lock",
        requested_by="user_admin",
        details={"model": "gpt-4o"},
    )
    assert req.status == ApprovalStatus.PENDING

    reviewed = mgr.review_request(req.request_id, approve=True, comments="Approved for production load test.")
    assert reviewed.status == ApprovalStatus.APPROVED
    assert reviewed.reviewer_comments == "Approved for production load test."


def test_c9_vs_c11_comparative_benchmark():
    harness = C9VsC11ComparativeBenchmark()
    res = harness.run_benchmark_suite()

    assert res["dod_17_satisfied"] is True
    assert res["overall_cost_reduction_pct"] >= 30.0
    assert res["overall_c11_avg_quality"] >= res["overall_c9_avg_quality"]
    assert "software_engineering" in res["family_breakdown"]
    assert "financial_modeling" in res["family_breakdown"]
