"""
Capability Registry Service.

Maintains system capability definitions and validates agent capability claims.
"""

from __future__ import annotations

from core.api.errors.exceptions import ConflictError, NotFoundError, ValidationError
from core.observability.logging import get_logger
from core.repositories import CapabilityRepository
from schemas.domain import Capability, CapabilityCreate


logger = get_logger("dsrt.capabilities")


class CapabilityRegistry:
    def __init__(self, repository: CapabilityRepository) -> None:
        self._repo = repository

    async def register_capability(self, data: CapabilityCreate) -> Capability:
        """Register a new capability in the system."""
        existing = await self._repo.get_by_slug(data.slug)
        if existing:
            raise ConflictError(
                f"Capability with slug '{data.slug}' already exists.",
                metadata={"slug": data.slug},
            )

        cap = await self._repo.create(
            slug=data.slug,
            name=data.name,
            description=data.description,
            version=data.version,
            input_schema=data.input_schema,
            output_schema=data.output_schema,
            requirements=data.requirements,
            risk_level=data.risk_level.value,
        )
        logger.info("capability_registered", slug=cap.slug, id=cap.id)
        return Capability.model_validate(cap, from_attributes=True)

    async def get_by_slug(self, slug: str) -> Capability:
        cap = await self._repo.get_by_slug(slug)
        if not cap:
            raise NotFoundError(
                f"Capability '{slug}' not found.", metadata={"slug": slug},
            )
        return Capability.model_validate(cap, from_attributes=True)

    async def list_all(self) -> list[Capability]:
        caps = await self._repo.list_all()
        return [Capability.model_validate(c, from_attributes=True) for c in caps]

    async def validate_capabilities_exist(self, slugs: list[str]) -> list[str]:
        """Validate that all requested capability slugs exist in the registry.

        Returns list of missing slugs if any.
        """
        if not slugs:
            return []
        found = await self._repo.get_by_slugs(slugs)
        found_slugs = {c.slug for c in found}
        missing = [s for s in slugs if s not in found_slugs]
        return missing