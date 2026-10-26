"""
Arena Metric Engine & Performance Profiles (C8 §24-32, §37, §64).

Computes metrics from evaluator outputs and assembles
multi-dimensional performance profiles.

Key principles:
  - Metrics are evidence-first (C8 §30)
  - No single quality score (C8 §2, §31)
  - Cost is separated by category (C8 §32)
  - Confidence includes sample size (C8 §37)
"""

from core.arena.metrics.computer import MetricComputer
from core.arena.metrics.profiles import PerformanceProfileBuilder

__all__ = ["MetricComputer", "PerformanceProfileBuilder"]