"""
Context Engine v2 (C4 §26-33, §46-48).

Orchestrates memory retrieval, applies context profiles, and delegates
to the C2 ContextCompiler for final token-bounded assembly.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from schemas.domain.context import ContextBuildRequest, ContextBuildResult, ContextProfile
from schemas.domain.context_compiler import CompiledContext, ContextBudget
from schemas.domain.memory import MemoryQuery
from schemas.domain.provider import ModelContextConfig

from core.context.profiles import ContextProfileManager
from core.kernel.fingerprint import content_hash
from core.memory.retrieval.engine import HybridRetrievalEngine
from core.models.context.compiler import ContextCompiler
from core.observability.logging import get_logger
from core.storage.identifiers import IdPrefix, new_id
from core.storage.models.context import ContextBuildORM
from sdk.agent import SDKAgentContext, SDKMemoryRecord, SDKToolResult


logger = get_logger("dsrt.context.engine")


class ContextEngine:
    """Assembles model context securely using memory retrieval and token budgeting."""

    def __init__(
        self,
        session: AsyncSession,
        retrieval_engine: HybridRetrievalEngine,
    ) -> None:
        self._session = session
        self._retrieval_engine = retrieval_engine

    async def build_context(
        self,
        request: ContextBuildRequest,
        agent_context: SDKAgentContext,
        model_config: ModelContextConfig,
        recent_tool_results: list[SDKToolResult] | None = None,
        conversation_history: list[Any] | None = None,
    ) -> tuple[CompiledContext, ContextBuildResult]:
        """Build the complete model context."""
        start_time = time.perf_counter()
        
        # 1. Resolve Profile
        profile = request.profile or ContextProfileManager.get_profile(request.agent_slug)

        # 2. Retrieve Relevant Memory
        retrieved_memories: list[SDKMemoryRecord] = []
        
        # Construct query based on the agent's objective and working state
        query_text = agent_context.objective
        if agent_context.working_state:
            # Append a summary of working state to improve retrieval relevance
            keys = ", ".join(agent_context.working_state.keys())
            query_text += f" Current state keys: {keys}"

        # Retrieve per requested scope
        for scope in request.memory_scopes:
            query = MemoryQuery(
                query=query_text,
                scope=scope,
                memory_types=request.memory_types,
                limit=profile.max_memory_items,
            )
            
            try:
                retrieval_resp = await self._retrieval_engine.search(
                    organization_id=request.organization_id,
                    query=query,
                )
                
                for res in retrieval_resp.results:
                    mem = res.memory
                    retrieved_memories.append(
                        SDKMemoryRecord(
                            id=mem.id,
                            memory_type=mem.memory_type.value,
                            content=mem.content,
                            scope=mem.scope_type.value,
                            metadata={
                                "relevance_score": res.relevance_score,
                                "retrieval_method": res.retrieval_method,
                            },
                        )
                    )
            except Exception as e:
                logger.warning(
                    "context_engine_retrieval_failed",
                    scope=scope.value,
                    error=str(e),
                )

        # 3. Configure Budget
        # Adjust base budget according to profile priorities
        budget = ContextBudget(
            output_reserve=request.output_reserve_tokens,
            memory_max_tokens=int(20000 * profile.semantic_memory_priority),
            history_max_tokens=int(20000 * profile.recent_events_priority),
        )

        # 4. Delegate to C2 ContextCompiler
        compiler = ContextCompiler(budget=budget)
        compiled = compiler.compile(
            agent_context=agent_context,
            model_config=model_config,
            memories=retrieved_memories,
            tool_results=recent_tool_results,
            conversation_history=conversation_history,
        )

        # 5. Build Audit Record
        context_hash_str = content_hash(str([m.model_dump() for m in compiled.messages]))
        
        memory_ids = [
            p.item_id for p in compiled.provenance if p.source_type == "memory"
        ]
        artifact_ids = [
            p.item_id for p in compiled.provenance if p.source_type == "artifact"
        ]
        
        duration_ms = int((time.perf_counter() - start_time) * 1000)

        build_result = ContextBuildResult(
            id=new_id(IdPrefix.CONTEXT_BUILD),
            execution_id=request.execution_id,
            task_id=request.task_id,
            context_hash=context_hash_str,
            total_tokens=compiled.total_tokens,
            memory_items_included=len(memory_ids),
            evidence_items_included=0,  # Reserved for C6
            artifact_items_included=len(artifact_ids),
            event_items_included=0,     # Reserved for C8 Trajectory
            memory_ids=memory_ids,
            artifact_ids=artifact_ids,
            retrieval_strategy="hybrid",
            compression_applied=False,  # C4.8 Compression placeholder
            state_dropped=compiled.state_dropped,
            build_time_ms=duration_ms,
            created_at=time.time(),
            updated_at=time.time(),
        )

        # Persist audit record
        orm = ContextBuildORM(
            id=build_result.id,
            execution_id=build_result.execution_id,
            task_id=build_result.task_id,
            context_hash=build_result.context_hash,
            total_tokens=build_result.total_tokens,
            memory_items_included=build_result.memory_items_included,
            evidence_items_included=build_result.evidence_items_included,
            artifact_items_included=build_result.artifact_items_included,
            event_items_included=build_result.event_items_included,
            memory_ids=build_result.memory_ids,
            artifact_ids=build_result.artifact_ids,
            retrieval_strategy=build_result.retrieval_strategy,
            compression_applied=build_result.compression_applied,
            state_dropped=build_result.state_dropped,
            build_time_ms=build_result.build_time_ms,
        )
        self._session.add(orm)
        await self._session.flush()

        logger.info(
            "context_engine_built_context",
            execution_id=request.execution_id,
            total_tokens=compiled.total_tokens,
            memories_included=len(memory_ids),
            duration_ms=duration_ms,
        )

        return compiled, build_result