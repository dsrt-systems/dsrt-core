"""
Research Intelligence Agent — Runtime Domain Models.

Pure dataclasses with zero Core dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ResearchStatus = Literal[
    "INITIALIZING",
    "PLANNING",
    "RESEARCHING",
    "ANALYZING",
    "VERIFYING",
    "FINALIZING",
    "COMPLETED",
    "FAILED",
]


ClaimStatus = Literal[
    "SUPPORTED",
    "PARTIALLY_SUPPORTED",
    "UNCERTAIN",
    "UNVERIFIED",
    "CONTRADICTED",
    "UNKNOWN",
]


@dataclass
class ResearchQuestion:
    id: str
    text: str
    priority: str = "medium"
    status: str = "PENDING"


@dataclass
class Source:
    id: str
    title: str
    url: str | None = None
    publisher: str | None = None


@dataclass
class Evidence:
    id: str
    source_id: str
    passage: str
    location: str | None = None


@dataclass
class Claim:
    id: str
    text: str
    question_id: str
    status: ClaimStatus = "UNVERIFIED"
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class Contradiction:
    id: str
    claim_a: str
    claim_b: str
    explanation: str
    status: str = "OPEN"


@dataclass
class Citation:
    id: str
    claim_id: str
    evidence_id: str
    source_id: str


@dataclass
class ResearchPlan:
    objective: str
    questions: list[ResearchQuestion]
    workflow: str = "standard_research"


@dataclass
class ResearchState:
    objective: str
    status: ResearchStatus = "INITIALIZING"
    plan: ResearchPlan | None = None
    questions: list[ResearchQuestion] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    verification_report: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchOutput:
    status: str
    title: str
    content: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)