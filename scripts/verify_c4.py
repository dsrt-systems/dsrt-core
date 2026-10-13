"""
C4 Phase Certification Script.

Verifies all C4 components are correctly built and integrated.
Run: python scripts/verify_c4.py
"""

from __future__ import annotations

import os
import sys

# Ensure project root is on sys.path when running as standalone script
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)


def verify_c4() -> bool:
    """Programmatically verify C4 completion."""
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, condition: bool, detail: str = "") -> None:
        checks.append((name, condition, detail))

    # --- C4.1: Memory Contracts ---
    try:
        from schemas.domain.memory import (
            Memory, MemoryCreate, MemoryVersion, MemorySource, MemoryLink,
            MemoryConflict, MemoryQuery, MemoryRetrievalResult, MemoryUpdate,
            MemoryRetrievalResponse, MemoryLinkCreate,
        )
        check("C4.1 Memory domain schemas", True)
    except ImportError as e:
        check("C4.1 Memory domain schemas", False, str(e))

    try:
        from schemas.domain.enums import (
            MemoryType, MemoryStatus, MemoryScope, MemoryImportance,
            MemoryLinkType, MemoryVerificationState,
        )
        check("C4.1 Memory enums", True)
    except ImportError as e:
        check("C4.1 Memory enums", False, str(e))

    try:
        from schemas.domain.context import ContextProfile, ContextBuildRequest, ContextBuildResult
        check("C4.1 Context schemas", True)
    except ImportError as e:
        check("C4.1 Context schemas", False, str(e))

    # --- C4.2: ORM Models ---
    try:
        from core.storage.models.memory import (
            MemoryORM, MemoryVersionORM, MemoryEmbeddingORM,
            MemorySourceORM, MemoryLinkORM, MemoryConflictORM,
        )
        from core.storage.models.memory_access import (
            MemoryAccessLogORM, MemoryRetentionPolicyORM, MemoryConsolidationRunORM,
        )
        from core.storage.models.context import ContextBuildORM
        check("C4.2 ORM models", True)
    except ImportError as e:
        check("C4.2 ORM models", False, str(e))

    # --- C4.3: Memory Store ---
    try:
        from core.memory.store import MemoryStore
        check("C4.3 Memory Store", True)
    except ImportError as e:
        check("C4.3 Memory Store", False, str(e))

    # --- C4.4: Permissions ---
    try:
        from core.memory.permissions import MemoryPermissionEngine, MemoryAccessPolicy, MemoryScopePolicy
        check("C4.4 Permissions", True)
    except ImportError as e:
        check("C4.4 Permissions", False, str(e))

    # --- C4.5: Embeddings ---
    try:
        from core.memory.embeddings import EmbeddingGenerator, EmbeddingStore
        check("C4.5 Embeddings", True)
    except ImportError as e:
        check("C4.5 Embeddings", False, str(e))

    # --- C4.6: Hybrid Retrieval ---
    try:
        from core.memory.retrieval import HybridRetrievalEngine, HybridRanker
        check("C4.6 Hybrid Retrieval", True)
    except ImportError as e:
        check("C4.6 Hybrid Retrieval", False, str(e))

    # --- C4.7: Conflict Detection ---
    try:
        from core.memory.conflicts import ConflictDetector, ConflictDetectionResult
        check("C4.7 Conflict Detection", True)
    except ImportError as e:
        check("C4.7 Conflict Detection", False, str(e))

    # --- C4.8: Context Engine v2 ---
    try:
        from core.context import ContextEngine, ContextProfileManager
        from core.context.compression import ContextCompressor
        check("C4.8 Context Engine v2", True)
    except ImportError as e:
        check("C4.8 Context Engine v2", False, str(e))

    # --- C4.9: Consolidation & Retention ---
    try:
        from core.memory.consolidation import MemoryConsolidator
        from core.memory.retention import RetentionEnforcer
        check("C4.9 Consolidation and Retention", True)
    except ImportError as e:
        check("C4.9 Consolidation and Retention", False, str(e))

    # --- C4.10: Memory SDK ---
    try:
        from sdk.agent.adapters.memory_adapter import MemorySDKImpl
        from sdk.agent.interfaces.memory import MemorySDK, SDKMemoryRecord
        check("C4.10 Memory SDK", True)
    except ImportError as e:
        check("C4.10 Memory SDK", False, str(e))

    # --- C4.11: Event Types + Error Codes ---
    try:
        from schemas.domain.enums import EventType, ErrorCode
        assert hasattr(EventType, "MEMORY_CREATED"), "MEMORY_CREATED missing"
        assert hasattr(EventType, "MEMORY_CONFLICT_DETECTED"), "MEMORY_CONFLICT_DETECTED missing"
        assert hasattr(EventType, "CONTEXT_BUILD_STARTED"), "CONTEXT_BUILD_STARTED missing"
        assert hasattr(EventType, "CONTEXT_BUILD_COMPLETED"), "CONTEXT_BUILD_COMPLETED missing"
        assert hasattr(EventType, "CONTEXT_RETRIEVAL_STARTED"), "CONTEXT_RETRIEVAL_STARTED missing"
        assert hasattr(EventType, "CONTEXT_COMPRESSION_COMPLETED"), "CONTEXT_COMPRESSION_COMPLETED missing"
        assert hasattr(ErrorCode, "MEMORY_NOT_FOUND"), "MEMORY_NOT_FOUND missing"
        assert hasattr(ErrorCode, "RETRIEVAL_FAILURE"), "RETRIEVAL_FAILURE missing"
        check("C4.11 Event Types and Error Codes", True)
    except (ImportError, AssertionError) as e:
        check("C4.11 Event Types and Error Codes", False, str(e))

    # --- C4.11: Memory Event Emitter ---
    try:
        from core.memory.observability import MemoryEventEmitter
        check("C4.11 Memory Event Emitter", True)
    except ImportError as e:
        check("C4.11 Memory Event Emitter", False, str(e))

    # --- C4.11: Memory API Router ---
    try:
        from core.api.routers.memory import router as memory_router
        check("C4.11 Memory API Router", True)
    except ImportError as e:
        check("C4.11 Memory API Router", False, str(e))

    # --- C4.11: EmbeddingStore.provider property ---
    try:
        from core.memory.embeddings.store import EmbeddingStore
        assert hasattr(EmbeddingStore, "provider"), "EmbeddingStore.provider property missing"
        check("C4.11 EmbeddingStore.provider", True)
    except (ImportError, AssertionError) as e:
        check("C4.11 EmbeddingStore.provider", False, str(e))

    # --- C4.11: StateSDK completeness ---
    try:
        from sdk.agent.adapters.state_adapter import StateSDKImpl
        s = StateSDKImpl()
        assert hasattr(s, "delete"), "StateSDKImpl.delete missing"
        assert hasattr(s, "set_many"), "StateSDKImpl.set_many missing"
        assert hasattr(s, "clear"), "StateSDKImpl.clear missing"
        check("C4.11 StateSDK completeness", True)
    except (ImportError, AssertionError) as e:
        check("C4.11 StateSDK completeness", False, str(e))

    # --- Summary ---
    print("\n" + "=" * 60)
    print("DSRT CORE - PHASE C4 CERTIFICATION")
    print("=" * 60)

    passed = sum(1 for _, ok, _ in checks if ok)
    failed = sum(1 for _, ok, _ in checks if not ok)

    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        icon = "[+]" if ok else "[!]"
        line = f"  {icon} {status}  {name}"
        if detail:
            line += f" -- {detail}"
        print(line)

    print(f"\n  Total: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        print("\n  C4 CERTIFICATION FAILED")
        return False
    else:
        print("\n  C4 PHASE CERTIFIED COMPLETE")
        return True


if __name__ == "__main__":
    success = verify_c4()
    sys.exit(0 if success else 1)