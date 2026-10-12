"""
Environment Runtime & Manager (C3 §33-38).

Top-level package for the DSRT Environment Fabric — the orchestration
layer that gives tools a controlled, lifecycle-managed place to run.
"""

from core.environments.lifecycle import (
    EnvironmentStatus,
    is_terminal_environment_status,
    validate_environment_transition,
)
from core.environments.manager.manager import EnvironmentManager
from core.environments.registry.registry import EnvironmentRegistry
from core.environments.runtime.base import EnvironmentRuntime

__all__ = [
    "EnvironmentManager",
    "EnvironmentRegistry",
    "EnvironmentRuntime",
    "EnvironmentStatus",
    "is_terminal_environment_status",
    "validate_environment_transition",
]