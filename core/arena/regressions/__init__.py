"""
Arena Regression & Analysis Engine (C8 §38-47).

Detects regressions across agent/model/world versions,
builds capability profiles, and analyzes failure patterns.
"""

from core.arena.regressions.detector import RegressionDetector
from core.arena.regressions.profiler import CapabilityProfiler
from core.arena.regressions.analyzer import FailureAnalyzer

__all__ = ["CapabilityProfiler", "FailureAnalyzer", "RegressionDetector"]