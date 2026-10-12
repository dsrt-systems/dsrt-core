"""
Evidence Analyzer — Extracts sources, evidence, claims, and citations from input.

C1 accepts a structured `evidence` array in the task input_payload (since C3 Tool Fabric
is not yet available for live web retrieval).
"""

from __future__ import annotations

from agents.research_intelligence.runtime.models import (
    Citation,
    Claim,
    Contradiction,
    Evidence,
    ResearchQuestion,
    ResearchState,
    Source,
)


class EvidenceAnalyzer:
    """Turns user-provided evidence blocks into structured Claims + Citations."""

    def analyze(
        self,
        state: ResearchState,
        input_payload: dict,
    ) -> None:
        """Populate state.sources / evidence / claims / citations in place."""
        raw_evidence = input_payload.get("evidence") or []
        if not isinstance(raw_evidence, list):
            return

        # Map each evidence block by index to a deterministic question by round-robin.
        questions = state.questions
        if not questions:
            return

        for idx, block in enumerate(raw_evidence):
            if not isinstance(block, dict):
                continue

            source_id = f"src_{idx + 1:03d}"
            evidence_id = f"ev_{idx + 1:03d}"
            claim_id = f"cl_{idx + 1:03d}"
            citation_id = f"cit_{idx + 1:03d}"

            source = Source(
                id=source_id,
                title=str(block.get("source_title", f"Source {idx + 1}")),
                url=block.get("source_url"),
                publisher=block.get("publisher"),
            )
            state.sources.append(source)

            evidence = Evidence(
                id=evidence_id,
                source_id=source_id,
                passage=str(block.get("passage", "")).strip(),
                location=block.get("location"),
            )
            state.evidence.append(evidence)

            target_question = questions[idx % len(questions)]
            claim_text = str(block.get("claim", "")).strip()
            if not claim_text:
                # Derive a minimal claim from the passage's first sentence.
                claim_text = evidence.passage.split(".")[0].strip() or "Unstated claim"

            claim = Claim(
                id=claim_id,
                text=claim_text,
                question_id=target_question.id,
                status="SUPPORTED" if evidence.passage else "UNVERIFIED",
                evidence_ids=[evidence_id],
            )
            state.claims.append(claim)

            citation = Citation(
                id=citation_id,
                claim_id=claim_id,
                evidence_id=evidence_id,
                source_id=source_id,
            )
            state.citations.append(citation)

        # Mark each question with a claim as ANSWERED; the rest go to unresolved.
        answered = {c.question_id for c in state.claims}
        for q in state.questions:
            if q.id in answered:
                q.status = "ANSWERED"
            else:
                q.status = "UNRESOLVED"
                state.unresolved_questions.append(q.id)

        # Detect contradictions declared by the user.
        raw_contra = input_payload.get("contradictions") or []
        for i, c in enumerate(raw_contra):
            if not isinstance(c, dict):
                continue
            claim_a = c.get("claim_a")
            claim_b = c.get("claim_b")
            if not claim_a or not claim_b:
                continue
            state.contradictions.append(
                Contradiction(
                    id=f"con_{i + 1:03d}",
                    claim_a=str(claim_a),
                    claim_b=str(claim_b),
                    explanation=str(c.get("explanation", "")),
                    status="OPEN",
                )
            )