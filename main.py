"""
DSRT Core — Application Entry Point

Starts the DSRT Core API server.
"""

from __future__ import annotations

import uvicorn

from core.config import get_settings


def main() -> None:
    """Start the DSRT Core server."""
    settings = get_settings()

    uvicorn.run(
        "core.api.app:create_app",
        factory=True,
        host=settings.api_host,
        port=settings.api_port,
        workers=settings.api_workers,
        reload=settings.api_reload,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()