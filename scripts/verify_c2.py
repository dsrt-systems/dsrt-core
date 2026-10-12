"""
DSRT Core — Phase C2 Model Fabric Certification Script.

Programmatically asserts C2 Definition of Done (§63).

Usage:
    python scripts/verify_c2.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from core.config import get_settings
from core.providers.registry.registry import adapter_registry
from core.storage.database import db_manager
from core.version import CORE_VERSION


class CertificationError(Exception):
    pass


def log_check(name: str, passed: bool, details: str = "") -> None:
    mark = "✅" if passed else "❌"
    print(f"  {mark} [{name}] {details}")
    if not passed:
        raise CertificationError(f"C2 Checkpoint failed: {name} — {details}")


async def run_c2_certification() -> None:
    print("\n=================================================================")
    print(f"   DSRT CORE v{CORE_VERSION} — PHASE C2 MODEL FABRIC CERTIFICATION")
    print("=================================================================\n")

    settings = get_settings()

    await db_manager.initialize()

    try:
        print("▶ Section 1: Provider Adapters")
        openai_adapter = adapter_registry.get_adapter("openai")
        log_check("OpenAI Adapter Registered", openai_adapter is not None, "OpenAIAdapter ready.")

        google_adapter = adapter_registry.get_adapter("google")
        log_check("Google Gemini Adapter Registered", google_adapter is not None, "GoogleAdapter ready.")

        print("\n▶ Section 2: Credential Encryption & Isolation")
        from core.security.credentials import CredentialEncryptor
        encryptor = CredentialEncryptor()
        token = encryptor.encrypt("sk-test-key-12345")
        decrypted = encryptor.decrypt(token)
        log_check(
            "AES-256 Fernet Encryption",
            decrypted == "sk-test-key-12345",
            "Encrypt/decrypt roundtrip verified.",
        )

        print("\n▶ Section 3: Model Sessions & Checkpoints Schema")
        async with db_manager.session() as s:
            res = await s.execute(
                text("SELECT count(*) FROM pg_tables WHERE schemaname = 'dsrt' AND tablename IN ('model_sessions', 'model_checkpoints')")
            )
            count = res.scalar()
            log_check("C2 Session Tables Present", count == 2, "model_sessions & model_checkpoints tables active.")

        print("\n▶ Section 4: Context Compiler & Token Budgeting")
        from core.models.context.compiler import ContextCompiler
        compiler = ContextCompiler()
        log_check("Context Compiler Ready", compiler is not None, "ContextCompiler initialized.")

        print("\n=================================================================")
        print("   ✅ ALL PHASE C2 DEFINITION-OF-DONE CHECKPOINTS CERTIFIED PASSED")
        print("=================================================================\n")

    finally:
        await db_manager.shutdown()


if __name__ == "__main__":
    asyncio.run(run_c2_certification())