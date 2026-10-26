"""
Phase C11.4: Context & Tool Configurator Component

Optimizes tool availability and context compilation parameters.
"""

from schemas.domain.agent_strategy import (
    ToolSelectionConfig,
    ContextCompilationConfig,
)
from schemas.domain.task_intelligence import TaskProfile, TaskComplexityLevel


class ContextToolConfigurator:
    """Configures tool availability and context budget constraints."""

    def configure_tools(self, profile: TaskProfile) -> ToolSelectionConfig:
        req_tools = profile.constraints.required_tools or []
        
        opt_tools = []
        if profile.classification.primary_domain.value == "software_engineering":
            opt_tools.extend(["code_executor", "linter", "git_repo_search"])
        elif profile.classification.primary_domain.value == "data_analysis":
            opt_tools.extend(["python_repl", "sql_executor"])

        max_invocations = 15 if profile.complexity.level in (TaskComplexityLevel.HIGH, TaskComplexityLevel.VERY_HIGH, TaskComplexityLevel.EXTREME) else 5

        return ToolSelectionConfig(
            required_tools=req_tools,
            optional_tools=[t for t in opt_tools if t not in req_tools],
            max_tool_invocations=max_invocations,
            timeout_per_tool_ms=10000.0,
        )

    def configure_context(self, profile: TaskProfile) -> ContextCompilationConfig:
        comp_level = profile.complexity.level

        if comp_level in (TaskComplexityLevel.TRIVIAL, TaskComplexityLevel.LOW):
            tokens = 2048
            strategy = "fifo"
        elif comp_level == TaskComplexityLevel.MEDIUM:
            tokens = 4096
            strategy = "fifo"
        else:
            tokens = 8192
            strategy = "relevance_summary"

        return ContextCompilationConfig(
            target_context_tokens=tokens,
            pruning_strategy=strategy,
            enable_code_stripping=(comp_level != TaskComplexityLevel.EXTREME),
            enable_retrieval_augmentation=(comp_level in (TaskComplexityLevel.HIGH, TaskComplexityLevel.VERY_HIGH, TaskComplexityLevel.EXTREME)),
        )