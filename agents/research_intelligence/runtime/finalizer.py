"""
Research Finalizer — Renders the research report artifact.

Produces the durable Markdown research report following OUTPUT_STANDARD.md.
"""

from __future__ import annotations

from agents.research_intelligence.runtime.models import ResearchState
from agents.research_intelligence.verification.verifier import (
    ResearchVerificationReport,
)


class ResearchFinalizer:
    """Renders the final research report artifact."""

    def render_report(
        self,
        state: ResearchState,
        verification: ResearchVerificationReport,
    ) -> str:
        lines: list[str] = []

        lines.append(f"# Research Report: {state.objective}")
        lines.append("")

        # Executive summary
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(
            f"This report addresses **{len(state.questions)} research question(s)** "
            f"using **{len(state.sources)} source(s)** and "
            f"**{len(state.evidence)} evidence passage(s)**, producing "
            f"**{len(state.claims)} claim(s)** with "
            f"**{len(state.citations)} citation(s)**."
        )
        if state.contradictions:
            lines.append(
                f"\n⚠️ **{len(state.contradictions)} contradiction(s)** were "
                f"surfaced and preserved for review."
            )
        lines.append("")

        # Scope
        lines.append("## Research Scope")
        lines.append("")
        lines.append(f"**Objective:** {state.objective}")
        lines.append("")

        # Methodology
        lines.append("## Methodology")
        lines.append("")
        lines.append(
            "- Objective decomposed into research questions.\n"
            "- Structured evidence extracted with provenance.\n"
            "- Claims cross-referenced to source evidence.\n"
            "- Contradictions preserved rather than resolved artificially.\n"
            "- Deterministic verification applied per agent policy."
        )
        lines.append("")

        # Findings (per question)
        lines.append("## Findings")
        lines.append("")
        for q in state.questions:
            lines.append(f"### {q.id.upper()} — {q.text}")
            lines.append(f"_Priority: {q.priority} · Status: {q.status}_")
            lines.append("")
            related_claims = [c for c in state.claims if c.question_id == q.id]
            if not related_claims:
                lines.append("_No claims produced for this question._")
                lines.append("")
                continue
            for c in related_claims:
                lines.append(f"- **{c.id}** ({c.status}): {c.text}")
            lines.append("")

        # Evidence table
        lines.append("## Evidence")
        lines.append("")
        if not state.evidence:
            lines.append("_No evidence collected._")
        else:
            lines.append("| Evidence ID | Source | Passage |")
            lines.append("|-------------|--------|---------|")
            for ev in state.evidence:
                src = next((s for s in state.sources if s.id == ev.source_id), None)
                src_name = src.title if src else "unknown"
                passage = (ev.passage[:120] + "…") if len(ev.passage) > 120 else ev.passage
                passage = passage.replace("|", "\\|").replace("\n", " ")
                lines.append(f"| {ev.id} | {src_name} | {passage} |")
        lines.append("")

        # Contradictions
        lines.append("## Contradictions")
        lines.append("")
        if not state.contradictions:
            lines.append("_No contradictions surfaced._")
        else:
            for con in state.contradictions:
                lines.append(
                    f"- **{con.id}** (status: {con.status}) — "
                    f"{con.claim_a} vs {con.claim_b}: {con.explanation}"
                )
        lines.append("")

        # Limitations
        lines.append("## Limitations")
        lines.append("")
        lines.append(
            "- C1 deterministic workflow: LLM-driven synthesis arrives with C2 Model Fabric.\n"
            "- Live tool retrieval arrives with C3 Tool Fabric.\n"
            "- Independent Core verification arrives with C6 Verification Fabric."
        )
        lines.append("")

        # Unresolved
        lines.append("## Unresolved Questions")
        lines.append("")
        if not state.unresolved_questions:
            lines.append("_All planned questions produced claims._")
        else:
            for qid in state.unresolved_questions:
                q = next((x for x in state.questions if x.id == qid), None)
                text = q.text if q else qid
                lines.append(f"- {qid}: {text}")
        lines.append("")

        # Conclusion
        lines.append("## Conclusion")
        lines.append("")
        lines.append(
            f"Verification status: **{verification.status}**. "
            f"{len(verification.failures)} failure(s), "
            f"{len(verification.warnings)} warning(s)."
        )
        lines.append("")

        # Sources
        lines.append("## Sources")
        lines.append("")
        if not state.sources:
            lines.append("_No sources referenced._")
        else:
            for s in state.sources:
                url = f" — {s.url}" if s.url else ""
                pub = f" ({s.publisher})" if s.publisher else ""
                lines.append(f"- **{s.id}**: {s.title}{pub}{url}")
        lines.append("")

        # Citation index
        lines.append("## Citation Index")
        lines.append("")
        if not state.citations:
            lines.append("_No citations._")
        else:
            for c in state.citations:
                lines.append(
                    f"- {c.id}: claim={c.claim_id} · evidence={c.evidence_id} · source={c.source_id}"
                )
        lines.append("")

        return "\n".join(lines)