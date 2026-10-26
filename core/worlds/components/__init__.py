"""
World Component System (C7 §10-11).

Pluggable components that compose a World. Each component wraps
an existing C3 capability behind a uniform lifecycle contract.

Components:
  - FilesystemComponent (wraps C3 WorkspaceManager)
  - BrowserComponent (wraps C3 browser tools)
  - TerminalComponent (wraps C3 shell tools)
  - RuntimeComponent (wraps C3 PythonSandbox)
  - DatabaseComponent (wraps C3 database tools)
"""

from core.worlds.components.component import (
    BaseWorldComponent,
    ComponentContext,
    ComponentHealth,
    ComponentSnapshot,
)
from core.worlds.components.filesystem import FilesystemComponent
from core.worlds.components.browser import BrowserComponent
from core.worlds.components.terminal import TerminalComponent
from core.worlds.components.runtime import RuntimeComponent
from core.worlds.components.database import DatabaseComponent
from core.worlds.components.manager import ComponentManager

__all__ = [
    "BaseWorldComponent",
    "BrowserComponent",
    "ComponentContext",
    "ComponentHealth",
    "ComponentManager",
    "ComponentSnapshot",
    "DatabaseComponent",
    "FilesystemComponent",
    "RuntimeComponent",
    "TerminalComponent",
]