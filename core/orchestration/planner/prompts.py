"""
Planning Prompt Templates (C5 §13, §62-63).

Templates for model-assisted plan generation. The model receives
the objective, available capabilities, and constraints, then produces
a structured plan in JSON format.

IMPORTANT: These prompts are capability-oriented, not domain-specific
(C5 §98). The model sees capabilities like 'web_research' and
'financial_analysis', not professions like 'researcher' or 'analyst'.
"""

from __future__ import annotations


PLAN_GENERATION_SYSTEM = """\
You are the DSRT Orchestration Planner. Your job is to decompose a user \
objective into an executable task graph (DAG) of nodes and dependencies.

RULES:
1. Each node must have a unique 
ode_key` (lowercase, underscores).
2. Each node must specify 
ode_type` from: AGENT_TASK, VERIFICATION, \
CONDITION, MERGE, CHECKPOINT, HUMAN_APPROVAL.
3. Each node must list `required_capabilities` — the capabilities needed \
to execute it. Use ONLY capabilities from the AVAILABLE CAPABILITIES list.
4. Dependencies must form a valid DAG (no cycles).
5. Use HARD dependencies unless a SOFT or CONDITION dependency is explicitly needed.
6. Keep the plan minimal — do not create unnecessary nodes.
7. Every plan must end with a VERIFICATION node.
8. If the objective is simple enough for a single agent, create a single \
AGENT_TASK node followed by a VERIFICATION node.

OUTPUT FORMAT (strict JSON):
{
  "nodes": [
    {
      "node_key": "string",
      "name": "string",
      "description": "string",
      "node_type": "AGENT_TASK",
      "required_capabilities": ["cap_1", "cap_2"],
      "depends_on": []
    }
  ],
  "dependencies": [
    {
      "source_node_key": "string",
      "target_node_key": "string",
      "dependency_type": "HARD"
    }
  ]
}

Output ONLY valid JSON. No markdown, no explanation, no commentary.\
"""


PLAN_GENERATION_USER = """\
OBJECTIVE: {objective}

AVAILABLE CAPABILITIES:
{capabilities}

CONSTRAINTS:
- Max nodes: {max_nodes}
- Max parallel: {max_parallel}
- Max depth: {max_depth}
- Allow delegation: {allow_delegation}

PREFERRED AGENTS: {preferred_agents}

ADDITIONAL CONTEXT:
{context}

Generate the task graph as JSON.\
"""


PLAN_REPAIR_SYSTEM = """\
You are the DSRT Orchestration Planner. Your previous plan was rejected \
by the validator. Fix the issues and produce a corrected plan.

VALIDATION ERRORS:
{errors}

VALIDATION WARNINGS:
{warnings}

ORIGINAL PLAN:
{original_plan}

Fix all errors and output the corrected plan as JSON. \
Follow the same rules as before.\
"""


def build_planning_prompt(
    objective: str,
    capabilities: list[str],
    constraints: dict,
    preferred_agents: list[str],
    context: str = "",
) -> tuple[str, str]:
    """Build the system and user prompts for plan generation.

    Returns:
        (system_prompt, user_prompt)
    """
    caps_text = "\n".join(f"  - {c}" for c in capabilities) or "  (none registered)"

    user = PLAN_GENERATION_USER.format(
        objective=objective,
        capabilities=caps_text,
        max_nodes=constraints.get("max_nodes", 100),
        max_parallel=constraints.get("max_parallel_nodes", 5),
        max_depth=constraints.get("max_depth", 20),
        allow_delegation=constraints.get("allow_delegation", True),
        preferred_agents=", ".join(preferred_agents) or "(any)",
        context=context or "(none)",
    )

    return PLAN_GENERATION_SYSTEM, user


def build_repair_prompt(
    errors: list[str],
    warnings: list[str],
    original_plan: str,
) -> tuple[str, str]:
    """Build prompts for repairing a failed plan."""
    system = PLAN_REPAIR_SYSTEM.format(
        errors="\n".join(f"  - {e}" for e in errors),
        warnings="\n".join(f"  - {w}" for w in warnings) or "  (none)",
        original_plan=original_plan,
    )
    user = "Fix the plan and output corrected JSON."
    return system, user