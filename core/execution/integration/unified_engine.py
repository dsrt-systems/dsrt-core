"""
UnifiedExecutionEngine — single entry facade for Work Mode and Comparison Mode.

Same infrastructure; protocol selection changes behavior.
Wires evaluation, economics, observability and comparison.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, List, Optional

from core.execution.integration.contracts import (
    ExecutionRequest,
    ExecutionResult,
    PreparedExecution,
    ProtocolExecutionResult,
    ValidationResult,
)
from core.execution.integration.dependencies import RuntimeDependencies, NullRuntimeDependencies
from core.execution.comparison.service import ComparisonService
from core.execution.comparison.contracts import ConfigurationRunEvidence


class ProtocolRegistry:
    """In-process registry of execution protocols."""

    def __init__(self) -> None:
        self._protocols: Dict[str, Any] = {}

    def register(self, protocol: Any) -> None:
        pid = getattr(protocol, "protocol_id", None)
        if not pid:
            raise ValueError("protocol must define protocol_id")
        self._protocols[str(pid)] = protocol

    def get(self, protocol_id: str) -> Any:
        if protocol_id not in self._protocols:
            raise KeyError(f"Unknown execution protocol: {protocol_id}")
        return self._protocols[protocol_id]

    def list_ids(self) -> List[str]:
        return list(self._protocols.keys())


class UnifiedExecutionEngine:
    """
    Central facade:
    create → validate → prepare → execute → evaluate/economics/trace → (compare) → finalize
    """

    def __init__(
        self,
        deps: Optional[RuntimeDependencies] = None,
        comparison_service: Optional[ComparisonService] = None,
        economics_engine: Any = None,
        evaluation_engine: Any = None,
        observability: Any = None,
    ):
        self.deps = deps or NullRuntimeDependencies()
        self.protocols = ProtocolRegistry()
        self.comparison = comparison_service or ComparisonService()
        self.economics = economics_engine
        self.evaluation = evaluation_engine
        self.observability = observability
        self._executions: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, ExecutionResult] = {}
        self._initialized: bool = False

    async def initialize(self) -> None:
        """Initialize the unified execution engine and external dependencies."""
        if self._initialized:
            return
        # Pre-warm optional subsystems when present
        if self.deps is not None and hasattr(self.deps, "initialize"):
            init_fn = getattr(self.deps, "initialize")
            result = init_fn()
            if hasattr(result, "__await__"):
                await result
        if self.observability is not None and hasattr(self.observability, "initialize"):
            init_fn = getattr(self.observability, "initialize")
            result = init_fn()
            if hasattr(result, "__await__"):
                await result
        self._initialized = True

    async def shutdown(self) -> None:
        """Gracefully shutdown the execution engine."""
        if not self._initialized:
            return
        if self.observability is not None and hasattr(self.observability, "shutdown"):
            stop_fn = getattr(self.observability, "shutdown")
            result = stop_fn()
            if hasattr(result, "__await__"):
                await result
        if self.deps is not None and hasattr(self.deps, "shutdown"):
            stop_fn = getattr(self.deps, "shutdown")
            result = stop_fn()
            if hasattr(result, "__await__"):
                await result
        self._executions.clear()
        self._results.clear()
        self._initialized = False

    def register_protocol(self, protocol: Any) -> None:
        self.protocols.register(protocol)

    async def create(self, request: ExecutionRequest) -> str:
        execution_id = str(uuid.uuid4())
        self._executions[execution_id] = {
            "execution_id": execution_id,
            "request": request,
            "status": "CREATED",
            "created_at": datetime.datetime.now(datetime.timezone.utc),
        }
        await self._emit("execution.created", request.workspace_id, execution_id, {})
        return execution_id

    async def validate(self, execution_id: str) -> ValidationResult:
        ctx = self._require(execution_id)
        request: ExecutionRequest = ctx["request"]
        ctx["status"] = "VALIDATING"
        await self._emit("execution.validating", request.workspace_id, execution_id, {})

        errors: List[str] = []
        if not request.workspace_id:
            errors.append("workspace_id is required")
        if not request.task_id:
            errors.append("task_id is required")
        if not request.protocol:
            errors.append("protocol is required")
        else:
            try:
                protocol = self.protocols.get(request.protocol)
            except KeyError:
                protocol = None
                if request.protocol not in {"direct", "amplified", "paired"}:
                    errors.append(f"unknown protocol: {request.protocol}")
            if protocol is not None and hasattr(protocol, "validate"):
                nested = await protocol.validate(request)
                if hasattr(nested, "errors"):
                    errors.extend(list(nested.errors or []))
                elif isinstance(nested, dict) and not nested.get("valid", True):
                    errors.extend(list(nested.get("errors") or []))

        if request.protocol == "paired":
            cfgs = request.configurations or []
            if len(cfgs) < 2:
                errors.append("paired protocol requires configurations with at least 2 entries")

        result = ValidationResult(valid=len(errors) == 0, errors=errors)
        ctx["validation"] = result
        if not result.valid:
            ctx["status"] = "FAILED"
        return result

    async def execute(self, execution_id: str) -> ExecutionResult:
        ctx = self._require(execution_id)
        request: ExecutionRequest = ctx["request"]

        validation = ctx.get("validation") or await self.validate(execution_id)
        if not validation.valid:
            result = ExecutionResult(
                execution_id=execution_id,
                workspace_id=request.workspace_id,
                task_id=request.task_id,
                protocol=request.protocol,
                status="FAILED",
                error="; ".join(validation.errors),
                completed_at=datetime.datetime.now(datetime.timezone.utc),
            )
            self._results[execution_id] = result
            return result

        ctx["status"] = "PREPARING"
        await self._emit("execution.preparing", request.workspace_id, execution_id, {})

        protocol = None
        try:
            protocol = self.protocols.get(request.protocol)
        except KeyError:
            protocol = None

        if protocol is not None and hasattr(protocol, "prepare"):
            prepared = await protocol.prepare(request)
            if isinstance(prepared, PreparedExecution):
                prepared_model = prepared
            else:
                prepared_model = PreparedExecution(
                    execution_id=execution_id,
                    workspace_id=request.workspace_id,
                    task_id=request.task_id,
                    protocol=request.protocol,
                    metadata=dict(prepared) if isinstance(prepared, dict) else {},
                )
        else:
            prepared_model = PreparedExecution(
                execution_id=execution_id,
                workspace_id=request.workspace_id,
                task_id=request.task_id,
                protocol=request.protocol,
            )

        prepared_model.execution_id = execution_id
        ctx["prepared"] = prepared_model
        ctx["status"] = "RUNNING"
        await self._emit("execution.started", request.workspace_id, execution_id, {})

        trace_id = str(uuid.uuid4())
        ctx["trace_id"] = trace_id
        if self.observability is not None:
            try:
                self.observability.get_or_create_collector(trace_id, execution_id)
            except Exception:
                pass

        if protocol is not None and hasattr(protocol, "execute"):
            proto_result = await protocol.execute(prepared_model)
            if not isinstance(proto_result, ProtocolExecutionResult):
                proto_result = ProtocolExecutionResult(
                    execution_id=execution_id,
                    protocol=request.protocol,
                    status=str(getattr(proto_result, "status", "COMPLETED")),
                    output=getattr(proto_result, "output", None),
                    error=getattr(proto_result, "error", None),
                    trace_id=trace_id,
                    metadata=proto_result if isinstance(proto_result, dict) else {},
                )
        else:
            proto_result = await self._builtin_execute(request, prepared_model, trace_id)

        ctx["protocol_result"] = proto_result
        ctx["status"] = "EVALUATING"

        evaluation_data = proto_result.evaluation
        economics_data = proto_result.economics
        comparison_data = None

        if evaluation_data is None and self.evaluation is not None:
            try:
                evaluation_data = await self._maybe_eval(request, proto_result)
            except Exception as exc:
                evaluation_data = {"error": str(exc), "overall_score": None}

        if economics_data is None and self.economics is not None:
            try:
                economics_data = await self._maybe_economics(request, proto_result)
            except Exception as exc:
                economics_data = {"error": str(exc)}

        if request.protocol == "paired":
            comparison_data = self._build_comparison(
                request, proto_result, evaluation_data, economics_data
            )
            await self._emit(
                "experiment.comparison.completed",
                request.workspace_id,
                execution_id,
                {"experiment_id": execution_id},
            )

        ctx["status"] = "FINALIZING"
        status = proto_result.status or "COMPLETED"
        if proto_result.error and status == "COMPLETED":
            status = "FAILED"

        result = ExecutionResult(
            execution_id=execution_id,
            workspace_id=request.workspace_id,
            task_id=request.task_id,
            protocol=request.protocol,
            status=status,
            output=proto_result.output,
            error=proto_result.error,
            trace_id=proto_result.trace_id or trace_id,
            evaluation=evaluation_data,
            economics=economics_data,
            comparison=comparison_data,
            artifacts=list(proto_result.artifacts or []),
            completed_at=datetime.datetime.now(datetime.timezone.utc),
            metadata=dict(proto_result.metadata or {}),
        )
        self._results[execution_id] = result
        ctx["status"] = status
        await self._emit(
            "execution.completed" if status == "COMPLETED" else "execution.failed",
            request.workspace_id,
            execution_id,
            {"status": status},
        )
        return result

    async def get_status(self, execution_id: str) -> Dict[str, Any]:
        ctx = self._require(execution_id)
        return {
            "execution_id": execution_id,
            "status": ctx.get("status"),
            "protocol": ctx["request"].protocol,
            "trace_id": ctx.get("trace_id"),
        }

    async def get_result(self, execution_id: str) -> Optional[ExecutionResult]:
        return self._results.get(execution_id)

    async def cancel(self, execution_id: str) -> None:
        ctx = self._require(execution_id)
        ctx["status"] = "CANCELLED"
        await self._emit("execution.cancelled", ctx["request"].workspace_id, execution_id, {})

    def _require(self, execution_id: str) -> Dict[str, Any]:
        if execution_id not in self._executions:
            raise KeyError(f"execution not found: {execution_id}")
        return self._executions[execution_id]

    async def _emit(
        self, event_type: str, workspace_id: str, execution_id: str, payload: Dict[str, Any]
    ) -> None:
        if self.observability is not None and hasattr(self.observability, "publisher"):
            try:
                from core.execution.observability.events import C10EventType

                et = None
                for member in C10EventType:
                    if member.value == event_type:
                        et = member
                        break
                if et is not None:
                    self.observability.publisher.publish(
                        event_type=et,
                        workspace_id=workspace_id,
                        execution_id=execution_id,
                        payload=payload,
                    )
                    return
            except Exception:
                pass
        if self.deps and self.deps.events is not None:
            try:
                await self.deps.events.publish(
                    event_type,
                    {
                        "workspace_id": workspace_id,
                        "execution_id": execution_id,
                        **payload,
                    },
                )
            except Exception:
                pass

    async def _builtin_execute(
        self,
        request: ExecutionRequest,
        prepared: PreparedExecution,
        trace_id: str,
    ) -> ProtocolExecutionResult:
        """
        Deterministic built-in path used when no external protocol adapter is registered.
        Enables integration tests and dry-runs without live providers.
        """
        if request.protocol == "paired":
            configs = request.configurations or [
                {"id": "baseline", "label": "Direct", "protocol": "direct"},
                {"id": "candidate", "label": "Amplified", "protocol": "amplified"},
            ]
            runs_meta = []
            for cfg in configs:
                runs_meta.append(
                    {
                        "configuration_id": cfg.get("id") or cfg.get("configuration_id"),
                        "configuration_label": cfg.get("label")
                        or cfg.get("configuration_label")
                        or cfg.get("id"),
                        "protocol": cfg.get("protocol", "direct"),
                        "succeeded": True,
                        "overall_score": cfg.get("overall_score", 0.8),
                        "total_cost_usd": cfg.get("total_cost_usd", 0.05),
                        "cost_availability": cfg.get("cost_availability", "ESTIMATED"),
                        "latency_ms": cfg.get("latency_ms", 1000),
                    }
                )
            return ProtocolExecutionResult(
                execution_id=prepared.execution_id,
                protocol="paired",
                status="COMPLETED",
                output="paired_execution_complete",
                trace_id=trace_id,
                metadata={"runs": runs_meta},
                run_evidence={"runs": runs_meta},
            )

        output = f"executed:{request.protocol}:{request.task_id}"
        return ProtocolExecutionResult(
            execution_id=prepared.execution_id,
            protocol=request.protocol,
            status="COMPLETED",
            output=output,
            trace_id=trace_id,
            evaluation={"overall_score": 1.0, "task_success": True},
            economics={"total_cost_usd": 0.01, "cost_availability": "ESTIMATED"},
        )

    async def _maybe_eval(
        self, request: ExecutionRequest, proto: ProtocolExecutionResult
    ) -> Dict[str, Any]:
        evaluate = getattr(self.evaluation, "evaluate", None)
        if evaluate is None:
            return proto.evaluation or {}
        payload = {
            "workspace_id": request.workspace_id,
            "task_id": request.task_id,
            "output": proto.output,
            "status": proto.status,
        }
        res = evaluate(payload)
        if hasattr(res, "__await__"):
            res = await res
        if hasattr(res, "model_dump"):
            return res.model_dump(mode="json")
        return dict(res) if isinstance(res, dict) else {"result": res}

    async def _maybe_economics(
        self, request: ExecutionRequest, proto: ProtocolExecutionResult
    ) -> Dict[str, Any]:
        summarize = getattr(self.economics, "summarize", None) or getattr(
            self.economics, "report", None
        )
        if summarize is None:
            return proto.economics or {}
        res = summarize(proto.execution_id) if callable(summarize) else None
        if hasattr(res, "__await__"):
            res = await res
        if hasattr(res, "model_dump"):
            return res.model_dump(mode="json")
        return dict(res) if isinstance(res, dict) else proto.economics or {}

    def _build_comparison(
        self,
        request: ExecutionRequest,
        proto: ProtocolExecutionResult,
        evaluation_data: Optional[Dict[str, Any]],
        economics_data: Optional[Dict[str, Any]],
    ) -> Dict[str, Any]:
        runs_raw = []
        if proto.run_evidence and isinstance(proto.run_evidence, dict):
            runs_raw = list(proto.run_evidence.get("runs") or [])
        if not runs_raw and isinstance(proto.metadata, dict):
            runs_raw = list(proto.metadata.get("runs") or [])

        evidence: List[ConfigurationRunEvidence] = []
        for item in runs_raw:
            if isinstance(item, ConfigurationRunEvidence):
                evidence.append(item)
                continue
            evidence.append(
                ConfigurationRunEvidence(
                    configuration_id=str(item.get("configuration_id") or item.get("id")),
                    configuration_label=str(
                        item.get("configuration_label")
                        or item.get("label")
                        or item.get("id")
                    ),
                    protocol=str(item.get("protocol") or "direct"),
                    execution_id=item.get("execution_id"),
                    run_status=str(
                        item.get("run_status")
                        or ("COMPLETED" if item.get("succeeded") else "FAILED")
                    ),
                    overall_score=item.get("overall_score"),
                    task_success=item.get("task_success", item.get("succeeded")),
                    correctness_score=item.get("correctness_score"),
                    completeness_score=item.get("completeness_score"),
                    reliability_score=item.get("reliability_score"),
                    total_cost_usd=item.get("total_cost_usd"),
                    cost_availability=str(item.get("cost_availability") or "UNAVAILABLE"),
                    latency_ms=item.get("latency_ms"),
                    succeeded=bool(item.get("succeeded", False)),
                    failed=bool(item.get("failed", False)),
                    error_count=int(item.get("error_count") or 0),
                    repair_count=int(item.get("repair_count") or 0),
                )
            )

        if len(evidence) < 2:
            for cfg in request.configurations or []:
                evidence.append(
                    ConfigurationRunEvidence(
                        configuration_id=str(cfg.get("id") or cfg.get("configuration_id")),
                        configuration_label=str(cfg.get("label") or cfg.get("id")),
                        protocol=str(cfg.get("protocol") or "direct"),
                        overall_score=cfg.get("overall_score"),
                        total_cost_usd=cfg.get("total_cost_usd"),
                        cost_availability=str(cfg.get("cost_availability") or "ESTIMATED"),
                        succeeded=bool(cfg.get("succeeded", True)),
                        task_success=cfg.get("task_success", True),
                        latency_ms=cfg.get("latency_ms"),
                    )
                )

        baseline_id = evidence[0].configuration_id if evidence else None

        result = self.comparison.compare_runs(
            experiment_id=proto.execution_id,
            workspace_id=request.workspace_id,
            runs=evidence,
            baseline_configuration_id=baseline_id,
            protocol_valid=len(evidence) >= 2,
            protocol_invalid_reasons=[] if len(evidence) >= 2 else ["insufficient_run_evidence"],
        )
        return self.comparison.report_dict(result)