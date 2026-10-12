"""
Context Compiler Engine (C2 §22-25).

Assembles canonical DSRT state into provider-compatible ModelContext.
Enforces context budgets, guarantees output reserves, and tracks provenance.
"""

from __future__ import annotations

import json

from core.models.context.token_counter import TokenCounter
from core.observability.logging import get_logger
from schemas.domain.context_compiler import (
    CompiledContext,
    ContextBudget,
    ContextProvenanceItem,
)
from schemas.domain.enums import MessageRole
from schemas.domain.model_fabric import ModelMessage
from schemas.domain.provider import ModelContextConfig
from sdk.agent import SDKAgentContext, SDKMemoryRecord, SDKToolResult


logger = get_logger("dsrt.models.context.compiler")


class ContextCompiler:
    """Compiles execution state into bounded model context."""

    def __init__(self, budget: ContextBudget | None = None) -> None:
        self.budget = budget or ContextBudget()

    def compile(
        self,
        *,
        agent_context: SDKAgentContext,
        model_config: ModelContextConfig,
        memories: list[SDKMemoryRecord] | None = None,
        tool_results: list[SDKToolResult] | None = None,
        conversation_history: list[ModelMessage] | None = None,
    ) -> CompiledContext:
        """Compile and pack context safely into the model's context window."""
        memories = memories or []
        tool_results = tool_results or []
        conversation_history = conversation_history or []

        provenance: list[ContextProvenanceItem] = []
        messages: list[ModelMessage] = []
        
        # 1. Determine absolute limits
        max_input = model_config.max_input_tokens
        reserved_output = min(model_config.max_output_tokens, self.budget.output_reserve)
        available_budget = max(0, max_input - reserved_output)
        
        current_tokens = 0
        state_dropped = False

        # 2. System Context (Highest Priority)
        system_context = {
            "agent_identity": {
                "slug": agent_context.agent_slug,
                "version": agent_context.agent_version,
            },
            "task_objective": agent_context.objective,
            "constraints": agent_context.constraints,
        }
        sys_tokens = TokenCounter.count_dict(system_context)
        current_tokens += sys_tokens
        
        if current_tokens > available_budget:
            # Utterly impossible to even fit the objective.
            raise ValueError(
                f"Context budget exceeded by base system prompt. "
                f"Requires {current_tokens}, available {available_budget}."
            )

        # 3. Working State (High Priority)
        if agent_context.working_state:
            state_text = json.dumps(agent_context.working_state)
            state_tokens = TokenCounter.count_text(state_text)
            
            if current_tokens + state_tokens <= available_budget:
                messages.append(
                    ModelMessage(
                        role=MessageRole.USER,
                        content=f"Current Working State:\n{state_text}",
                    )
                )
                current_tokens += state_tokens
                provenance.append(
                    ContextProvenanceItem(
                        item_id=agent_context.execution_id,
                        source_type="working_state",
                        original_size_tokens=state_tokens,
                        included_size_tokens=state_tokens,
                    )
                )
            else:
                state_dropped = True

        # 4. Tool Results (Medium Priority)
        if tool_results:
            tool_content = ""
            for tr in tool_results:
                tr_str = f"Tool '{tr.tool_slug}' Result: {tr.status}\n{tr.output}\n\n"
                tr_tokens = TokenCounter.count_text(tr_str)
                
                if current_tokens + tr_tokens <= available_budget:
                    tool_content += tr_str
                    current_tokens += tr_tokens
                    provenance.append(
                        ContextProvenanceItem(
                            item_id=tr.tool_slug,
                            source_type="tool_result",
                            original_size_tokens=tr_tokens,
                            included_size_tokens=tr_tokens,
                        )
                    )
                else:
                    # Try to truncate
                    remaining = available_budget - current_tokens
                    if remaining > 20:
                        trunc_str, _ = TokenCounter.truncate_text(tr_str, remaining)
                        tool_content += trunc_str
                        current_tokens += TokenCounter.count_text(trunc_str)
                        provenance.append(
                            ContextProvenanceItem(
                                item_id=tr.tool_slug,
                                source_type="tool_result",
                                original_size_tokens=tr_tokens,
                                included_size_tokens=remaining,
                                was_truncated=True,
                            )
                        )
                    state_dropped = True
                    break
            
            if tool_content:
                messages.append(
                    ModelMessage(
                        role=MessageRole.USER,
                        content=f"Recent Tool Observations:\n{tool_content}",
                    )
                )

        # 5. Memories (Lower Priority)
        if memories:
            memory_content = ""
            for mem in memories:
                mem_str = f"Memory ({mem.memory_type}): {mem.content}\n"
                mem_tokens = TokenCounter.count_text(mem_str)
                
                if current_tokens + mem_tokens <= available_budget:
                    memory_content += mem_str
                    current_tokens += mem_tokens
                    provenance.append(
                        ContextProvenanceItem(
                            item_id=mem.id or "unknown",
                            source_type="memory",
                            original_size_tokens=mem_tokens,
                            included_size_tokens=mem_tokens,
                        )
                    )
                else:
                    state_dropped = True
                    break
            
            if memory_content:
                messages.append(
                    ModelMessage(
                        role=MessageRole.USER,
                        content=f"Relevant Memory:\n{memory_content}",
                    )
                )

        # 6. Conversation History (Lowest Priority in C2 - Truncated from oldest if needed)
        if conversation_history:
            history_messages: list[ModelMessage] = []
            
            # Walk backwards from most recent message
            for msg in reversed(conversation_history):
                msg_tokens = TokenCounter.count_text(str(msg.content))
                if current_tokens + msg_tokens <= available_budget:
                    history_messages.insert(0, msg)
                    current_tokens += msg_tokens
                else:
                    state_dropped = True
                    break
            
            messages.extend(history_messages)

        # Ensure we always have at least one message for the model
        if not messages:
            messages.append(
                ModelMessage(
                    role=MessageRole.USER,
                    content="Begin task execution.",
                )
            )

        logger.debug(
            "context_compiled",
            execution_id=agent_context.execution_id,
            total_tokens=current_tokens,
            available_budget=available_budget,
            state_dropped=state_dropped,
            provenance_items=len(provenance),
        )

        return CompiledContext(
            messages=messages,
            system_context=system_context,
            total_tokens=current_tokens,
            output_budget_reserved=reserved_output,
            provenance=provenance,
            state_dropped=state_dropped,
        )