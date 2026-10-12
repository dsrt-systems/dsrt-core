"""
Research Planner — Deterministic decomposition of the objective.

C1 uses rule-based decomposition (C2 will add LLM-assisted planning).
"""

from __future__ import annotations

import uuid

from agents.research_intelligence.runtime.models import (
    ResearchPlan,
    ResearchQuestion,
)


class ResearchPlanner:
    """Decomposes an objective into a research plan."""

    def __init__(self, min_questions: int = 2, max_questions: int = 6) -> None:
        self._min_questions = min_questions
        self._max_questions = max_questions

    def create_plan(
        self,
        objective: str,
        input_payload: dict,
    ) -> ResearchPlan:
        """Produce a ResearchPlan from the user's objective and input payload."""
        provided = input_payload.get("questions") or []
        questions: list[ResearchQuestion] = []

        # Ingest user-provided questions first.
        for i, q in enumerate(provided[: self._max_questions]):
            text = q if isinstance(q, str) else q.get("text", "")
            if not text.strip():
                continue
            questions.append(
                ResearchQuestion(
                    id=f"q_{i + 1:03d}",
                    text=text.strip(),
                    priority="high" if i == 0 else "medium",
                )
            )

        # Ensure we always have at least min_questions from a deterministic decomposition.
        if len(questions) < self._min_questions:
            base = objective.strip().rstrip(".?!")
            fallback_templates = [
                f"What is the current state of: {base}?",
                f"What evidence is available regarding: {base}?",
                f"What are the key stakeholders or factors in: {base}?",
                f"What are the primary risks or uncertainties in: {base}?",
            ]
            for i, tmpl in enumerate(fallback_templates):
                if len(questions) >= self._min_questions:
                    break
                q_id = f"q_{len(questions) + 1:03d}"
                questions.append(
                    ResearchQuestion(
                        id=q_id,
                        text=tmpl,
                        priority="high" if not questions else "medium",
                    )
                )

        return ResearchPlan(
            objective=objective,
            questions=questions,
            workflow="standard_research",
        )