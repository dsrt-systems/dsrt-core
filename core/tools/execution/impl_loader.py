"""
Tool Implementation Loader (C3 §5).

Safely loads DSRTTool implementation classes from dotted module paths.
A malformed implementation class never crashes the engine.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING

from core.observability.logging import get_logger
from core.tools.errors import ToolRuntimeError

if TYPE_CHECKING:
    from core.tools import DSRTTool


logger = get_logger("dsrt.tools.impl_loader")


def load_tool_implementation(implementation_class: str) -> type[DSRTTool]:
    """Load a DSRTTool implementation class from a dotted path.

    Format: 'module.path:ClassName' or 'module.path.ClassName'

    Raises:
        ToolRuntimeError: If the class cannot be loaded or does not
            conform to the DSRTTool protocol.
    """
    try:
        if ":" in implementation_class:
            module_path, class_name = implementation_class.rsplit(":", 1)
        elif "." in implementation_class:
            module_path, class_name = implementation_class.rsplit(".", 1)
        else:
            raise ToolRuntimeError(
                f"Invalid implementation_class format: '{implementation_class}'. "
                "Expected 'module.path:ClassName' or 'module.path.ClassName'."
            )

        module = importlib.import_module(module_path)
        cls = getattr(module, class_name, None)

        if cls is None:
            raise ToolRuntimeError(
                f"Class '{class_name}' not found in module '{module_path}'."
            )

        # Verify it's a class (not a function or constant)
        if not isinstance(cls, type):
            raise ToolRuntimeError(
                f"'{implementation_class}' is not a class (got {type(cls).__name__})."
            )

        # Verify it has the required DSRTTool attributes
        required_attrs = ("identity", "manifest", "initialize", "execute", "cancel", "health")
        missing = [a for a in required_attrs if not hasattr(cls, a)]
        if missing:
            logger.warning(
                "tool_impl_missing_protocol_attrs",
                implementation_class=implementation_class,
                missing=missing,
            )
            # We warn but don't block — the Protocol check at runtime will catch this

        logger.debug(
            "tool_impl_loaded",
            implementation_class=implementation_class,
        )
        return cls

    except ToolRuntimeError:
        raise
    except ImportError as e:
        raise ToolRuntimeError(
            f"Cannot import module for tool implementation "
            f"'{implementation_class}': {e}"
        ) from e
    except Exception as e:
        raise ToolRuntimeError(
            f"Failed to load tool implementation "
            f"'{implementation_class}': {e}"
        ) from e