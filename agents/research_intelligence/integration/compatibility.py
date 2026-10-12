"""Compatibility validation for research_intelligence."""

from __future__ import annotations

from core.version import AGENT_CONTRACT_VERSION, CORE_VERSION

CORE_MINIMUM_VERSION = "1.0.0"
EXPECTED_CONTRACT_VERSION = "1.0"


def validate_compatibility() -> None:
    """Raise RuntimeError if the running Core is incompatible."""
    if CORE_VERSION < CORE_MINIMUM_VERSION:
        raise RuntimeError(
            f"research_intelligence requires Core >= {CORE_MINIMUM_VERSION}, "
            f"but Core is {CORE_VERSION}."
        )
    if AGENT_CONTRACT_VERSION != EXPECTED_CONTRACT_VERSION:
        raise RuntimeError(
            f"research_intelligence expects contract "
            f"{EXPECTED_CONTRACT_VERSION}, but Core exposes {AGENT_CONTRACT_VERSION}."
        )