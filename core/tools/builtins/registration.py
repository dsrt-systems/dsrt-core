"""
Built-in Tool Registration.

Registers all built-in DSRT tools in the Tool Registry during startup
or on-demand (e.g., in tests).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.observability.logging import get_logger
from core.repositories.tool_repository import ToolRepository
from core.tools.builtins.http_request import HttpRequestTool
from core.tools.builtins.web_retrieve import WebRetrieveTool
from core.tools.builtins.web_search import WebSearchTool
from core.tools.registry.registry import ToolRegistry

from core.tools.builtins.filesystem_delete import FilesystemDeleteTool
from core.tools.builtins.filesystem_list import FilesystemListTool
from core.tools.builtins.filesystem_move import FilesystemMoveTool
from core.tools.builtins.filesystem_promote import FilesystemPromoteToArtifactTool
from core.tools.builtins.filesystem_read import FilesystemReadTool
from core.tools.builtins.filesystem_stat import FilesystemStatTool
from core.tools.builtins.filesystem_write import FilesystemWriteTool
from core.tools.builtins.python_execute import PythonExecuteTool

logger = get_logger("dsrt.tools.builtins.registration")


_BUILTIN_TOOLS = [
    (WebSearchTool, "core.tools.builtins.web_search:WebSearchTool"),
    (WebRetrieveTool, "core.tools.builtins.web_retrieve:WebRetrieveTool"),
    (HttpRequestTool, "core.tools.builtins.http_request:HttpRequestTool"),
    (FilesystemReadTool, "core.tools.builtins.filesystem_read:FilesystemReadTool"),
    (FilesystemWriteTool, "core.tools.builtins.filesystem_write:FilesystemWriteTool"),
    (FilesystemListTool, "core.tools.builtins.filesystem_list:FilesystemListTool"),
    (FilesystemDeleteTool, "core.tools.builtins.filesystem_delete:FilesystemDeleteTool"),
    (FilesystemMoveTool, "core.tools.builtins.filesystem_move:FilesystemMoveTool"),
    (FilesystemStatTool, "core.tools.builtins.filesystem_stat:FilesystemStatTool"),
    (FilesystemPromoteToArtifactTool, "core.tools.builtins.filesystem_promote:FilesystemPromoteToArtifactTool"),
    (PythonExecuteTool, "core.tools.builtins.python_execute:PythonExecuteTool"),
]


async def register_builtin_tools(session: AsyncSession) -> dict[str, str]:
    """Register all built-in tools in the Registry (idempotent).

    Returns a mapping of {tool_slug: outcome} where outcome is
    "registered" or "already_present".
    """
    repo = ToolRepository(session)
    registry = ToolRegistry(repo)
    results: dict[str, str] = {}

    for tool_cls, impl_path in _BUILTIN_TOOLS:
        slug = tool_cls.identity.slug
        version = tool_cls.identity.version

        # Check if this tool + version already registered
        existing_tool = await repo.get_by_slug(slug)
        if existing_tool:
            existing_version = await repo.get_version(existing_tool.id, version)
            if existing_version:
                results[slug] = "already_present"
                logger.debug(
                    "builtin_tool_already_registered",
                    slug=slug,
                    version=version,
                )
                continue

        # Register the tool
        try:
            await registry.register_tool(
                manifest=tool_cls.manifest,
                implementation_class=impl_path,
                make_active=True,
            )
            results[slug] = "registered"
            logger.info(
                "builtin_tool_registered",
                slug=slug,
                version=version,
                implementation=impl_path,
            )
        except Exception as e:
            logger.warning(
                "builtin_tool_registration_failed",
                slug=slug,
                error=str(e),
            )
            results[slug] = f"error: {e}"

    return results