"""
Claim Extractor (C6 §14).

Deterministic claim extraction: reads claims EXPLICITLY declared in
structured agent output. It never invents claims from prose —
model-assisted extraction is a separate, later capability and will be
clearly labeled when it arrives.

Expected output shape:
    {"claims": [
        {"statement": "...", "source_refs": ["evd_...", "https://..."],
         "importance": "normal"},
    ]}
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.observability.logging import get_logger
from schemas.domain.enums import EventType
from schemas.domain.verification import Claim

logger = get_logger("dsrt.verification.claims.extractor")

VALID_IMPORTANCE = frozenset({"low", "normal", "high", "critical"})
MAX_STATEMENT_LENGTH = 10_000


@dataclass(frozen=True)
class ExtractedClaim:
    statement: str
    source_refs: list[str] = field(default_factory=list)
    importance: str = "normal"


@dataclass(frozen=True)
class ExtractionResult:
    claims: list[ExtractedClaim] = field(default_factory=list)
    rejected: list[tuple[int, str]] = field(default_factory=list)


class ClaimExtractor:

    def extract_from_output(self, output) -> ExtractionResult:
        if not isinstance(output, dict):
            return ExtractionResult()
        raw = output.get("claims")
        if raw is None:
            return ExtractionResult()
        if not isinstance(raw, list):
            return ExtractionResult(rejected=[(0, "'claims' must be a list.")])

        claims: list[ExtractedClaim] = []
        rejected: list[tuple[int, str]] = []

        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                rejected.append((i, "claim entry must be an object."))
                continue

            statement = item.get("statement")
            if not isinstance(statement, str) or not statement.strip():
                rejected.append((i, "claim 'statement' must be a non-empty string."))
                continue
            if len(statement) > MAX_STATEMENT_LENGTH:
                rejected.append((i, f"statement exceeds {MAX_STATEMENT_LENGTH} chars."))
                continue

            refs = item.get("source_refs", [])
            if not isinstance(refs, list) or not all(
                isinstance(r, str) and r.strip() for r in refs
            ):
                rejected.append((i, "'source_refs' must be a list of non-empty strings."))
                continue

            importance = item.get("importance", "normal")
            if importance not in VALID_IMPORTANCE:
                rejected.append(
                    (i, f"importance '{importance}' not in {sorted(VALID_IMPORTANCE)}.")
                )
                continue

            claims.append(
                ExtractedClaim(
                    statement=statement.strip(),
                    source_refs=[r.strip() for r in refs],
                    importance=importance,
                )
            )

        return ExtractionResult(claims=claims, rejected=rejected)

    async def persist(
        self,
        extraction: ExtractionResult,
        *,
        session,
        execution_id: str,
        organization_id: str,
        node_execution_id: str | None = None,
        kernel=None,
    ) -> list[Claim]:
        from core.repositories.claim_repository import ClaimRepository
        from core.storage.models.claim import ClaimORM

        repo = ClaimRepository(session)
        persisted: list[Claim] = []

        for extracted in extraction.claims:
            existing = await repo.find_by_statement(
                execution_id=execution_id, statement=extracted.statement,
            )
            if existing:
                continue

            orm = await repo.create(
                organization_id=organization_id,
                execution_id=execution_id,
                statement=extracted.statement,
                source_refs=extracted.source_refs,
                importance=extracted.importance,
                node_execution_id=node_execution_id,
            )
            persisted.append(self._to_domain(orm))

            if kernel:
                try:
                    await kernel.emit_event(
                        execution_id=execution_id,
                        event_type=EventType.CLAIM_CREATED,
                        source="dsrt.verification.claims",
                        payload={
                            "claim_id": orm.id,
                            "importance": extracted.importance,
                            "source_ref_count": len(extracted.source_refs),
                        },
                    )
                except Exception as e:
                    logger.warning(
                        "claim_created_event_failed",
                        claim_id=orm.id, error=str(e),
                    )

        if extraction.rejected:
            logger.warning(
                "claim_extraction_rejections",
                count=len(extraction.rejected),
                rejected=extraction.rejected[:10],
            )
        return persisted

    @staticmethod
    def _to_domain(orm) -> Claim:
        return Claim(
            id=orm.id,
            execution_id=orm.execution_id,
            node_execution_id=orm.node_execution_id,
            statement=orm.statement,
            source_refs=orm.source_refs or [],
            importance=orm.importance,
            status=orm.status,
            uncertainty=orm.uncertainty,
            metadata=orm.metadata_json or {},
        )