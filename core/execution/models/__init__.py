"""
C10.6 — Model Resolution & Profile Registry.

Provides canonical model identity (fingerprints), resolved model
connections, three-layer profile storage, and tiered profiling.
"""

from core.execution.models.fingerprint import (
    ModelFingerprint,
    ModelFingerprinter,
    FingerprintField,
)
from core.execution.models.resolver import (
    ModelResolver,
    ResolvedModelConnection,
    ResolutionError,
    ConnectionSource,
)
from core.execution.models.profiles import (
    ProfileRegistry,
    SharedProfileService,
    ConnectionProfileService,
    ExecutionProfileService,
)
from core.execution.models.profiling import (
    TieredProfilingOrchestrator,
    ProfilingRequest,
    ProfilingResult,
    ProfilingDecision,
)

__all__ = [
    # fingerprint
    "ModelFingerprint",
    "ModelFingerprinter",
    "FingerprintField",
    # resolver
    "ModelResolver",
    "ResolvedModelConnection",
    "ResolutionError",
    "ConnectionSource",
    # profiles
    "ProfileRegistry",
    "SharedProfileService",
    "ConnectionProfileService",
    "ExecutionProfileService",
    # profiling
    "TieredProfilingOrchestrator",
    "ProfilingRequest",
    "ProfilingResult",
    "ProfilingDecision",
]