# core/routing/types.py
"""
C9 type aliases for routing contracts.
"""

from typing import Any

# JSON-serialisable dict used in JSONB columns and evidence payloads
RoutingMetrics = dict[str, Any]
ConstraintDict = dict[str, Any]
PreferenceDict = dict[str, Any]
EvidenceRefs = list[str]
ToolList = list[str]
DimensionScores = dict[str, float]