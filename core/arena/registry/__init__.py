"""
Arena Registry Services (C8 §5-12, §48-51).

Benchmark, Task Suite, and Task Definition management.
"""

from core.arena.registry.benchmark_registry import BenchmarkRegistry
from core.arena.registry.task_registry import TaskRegistry

__all__ = ["BenchmarkRegistry", "TaskRegistry"]