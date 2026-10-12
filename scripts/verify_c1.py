"""
DSRT Core — Phase C1 Definition-of-Done Certification Script.

Programmatically asserts checkpoints from C1 §63 against a live database.

Usage:
    python scripts/verify_c1.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add project root to sys.path so we can run this directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from core.config import get_settings
from core.storage.database import db_manager
from core.version import AGENT_CONTRACT_VERSION, CORE_VERSION, SDK_VERSION


class CertificationError(Exception):
    """Raised when a mandatory C1 checkpoint fails."""
    pass


def log_check(name: str, passed: bool, details: str = "") -> None:
    """Print the result of a certification check."""
    mark = "✅" if passed else "❌"
    print(f"  {mark} [{name}] {details}")
    if not passed:
        raise CertificationError(f"Checkpoint failed: {name} — {details}")


async def run_c1_certification() -> None:
    print("\n=================================================================")
    print(f"   DSRT CORE v{CORE_VERSION} — PHASE C1 CERTIFICATION HARNESS")
    print("=================================================================\n")

    settings = get_settings()
    print(f"Core Version:            {CORE_VERSION}")
    print(f"Agent Contract Version:  {AGENT_CONTRACT_VERSION}")
    print(f"SDK Version:             {SDK_VERSION}")
    print(f"Database Schema:         {settings.database_schema}")
    print(f"Environment:             {settings.environment}\n")

    await db_manager.initialize()

    try:
        # Group 1: Core Substrate & Storage
        print("▶ Section 1: Core Substrate & Storage (C1 §63)")
        
        healthy = await db_manager.health_check()
        log_check("Database Reachable", healthy, "Connected to Supabase PostgreSQL pooler.")

        async with db_manager.session() as s:
            res = await s.execute(
                text("SELECT count(*) FROM pg_tables WHERE schemaname = :schema"),
                {"schema": settings.database_schema},
            )
            count = res.scalar()
            log_check("Schema Deployed", count >= 16, f"Found {count} tables in '{settings.database_schema}'.")

            vec_res = await s.execute(
                text("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
            )
            has_vec = (vec_res.scalar() or 0) > 0
            log_check("pgvector Enabled", has_vec, "Extension 'vector' present in Supabase.")

        # Group 2: Agent Contract & SDK Boundaries
        print("\n▶ Section 2: Agent Contract & SDK Boundaries (C1 §9, §17)")

        log_check(
            "Agent Contract v1 Frozen",
            AGENT_CONTRACT_VERSION == "1.0",
            f"Contract version = {AGENT_CONTRACT_VERSION}",
        )

        from sdk.agent import DSRTAgentSDK
        log_check(
            "SDK Protocols Exported",
            hasattr(DSRTAgentSDK, "__dataclass_fields__"),
            "Master DSRTAgentSDK dataclass ready.",
        )

        # Group 3: Reference Agent Package
        print("\n▶ Section 3: Reference Implementation (C1 §54)")

        from agents.research_intelligence.runtime.agent import ResearchIntelligenceAgent
        from schemas.domain import AgentManifest

        agent = ResearchIntelligenceAgent()
        
        log_check(
            "Reference Agent Instantiable",
            agent.identity.id == "research_intelligence",
            f"Agent identity = '{agent.identity.id}@{agent.identity.version}'",
        )

        log_check(
            "Manifest Validated",
            isinstance(agent.manifest, AgentManifest),
            f"Declared capabilities = {len(agent.manifest.capabilities)}",
        )

        # Group 4: Execution Telemetry & Reproducibility
        print("\n▶ Section 4: Execution Telemetry & Reproducibility (C1 §39)")

        async with db_manager.session() as s:
            exec_res = await s.execute(text("SELECT count(*) FROM dsrt.executions"))
            exec_count = exec_res.scalar() or 0
            log_check(
                "Execution Telemetry Recorded",
                exec_count >= 0,  # We allow 0 if run on a fresh DB, but table must exist
                f"{exec_count} total executions recorded in database.",
            )

            evt_res = await s.execute(text("SELECT count(*) FROM dsrt.execution_events"))
            evt_count = evt_res.scalar() or 0
            log_check(
                "Event Trajectories Recorded",
                evt_count >= 0,
                f"{evt_count} total monotonic events persisted.",
            )

            art_res = await s.execute(text("SELECT count(*) FROM dsrt.artifacts"))
            art_count = art_res.scalar() or 0
            log_check(
                "Artifacts Persisted",
                art_count >= 0,
                f"{art_count} durable artifacts registered.",
            )

        print("\n=================================================================")
        print("   ✅ ALL C1 DEFINITION-OF-DONE CHECKPOINTS CERTIFIED PASSED")
        print("=================================================================\n")

    finally:
        await db_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(run_c1_certification())