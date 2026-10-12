"""
Context Engine v2 (C4 §26-33, §46-48).

Assembles model context securely using memory retrieval, budgeting,
and provenance tracking.
"""

from core.context.engine import ContextEngine
from core.context.profiles import ContextProfileManager

__all__ = ["ContextEngine", "ContextProfileManager"]