"""
DSRT Core API Application Factory.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.api.errors import register_error_handlers
from core.api.routers import (
    agents as agents_router,
    artifacts as artifacts_router,
    auth as auth_router,
    capabilities as capabilities_router,
    credentials as credentials_router,
    events as events_router,
    executions as executions_router,
    providers as providers_router,
    tasks as tasks_router,
)
from core.config import get_settings
from core.observability.logging import get_logger, setup_logging
from core.observability.middleware import ObservabilityMiddleware
from core.storage.database import db_manager
from core.version import AGENT_CONTRACT_VERSION, CORE_VERSION, SDK_VERSION


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan manager — startup and shutdown."""
    logger = get_logger("dsrt.core")

    logger.info(
        "dsrt_core_starting",
        core_version=CORE_VERSION,
        agent_contract_version=AGENT_CONTRACT_VERSION,
        sdk_version=SDK_VERSION,
        environment=get_settings().environment,
    )

    await db_manager.initialize()

    db_healthy = await db_manager.health_check()
    if not db_healthy:
        logger.error("database_health_check_failed_on_startup")
        raise RuntimeError(
            "Database is not reachable — cannot start DSRT Core."
        )

    logger.info("dsrt_core_ready")

    yield

    logger.info("dsrt_core_shutting_down")
    await db_manager.shutdown()


def create_app() -> FastAPI:
    """Create the DSRT Core FastAPI application."""
    settings = get_settings()

    setup_logging()

    app = FastAPI(
        title="DSRT Core",
        description=(
            "DSRT Open Arena — Model-Independent Intelligence Execution System"
        ),
        version=CORE_VERSION,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.debug else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(ObservabilityMiddleware)

    register_error_handlers(app)

    # --- System endpoints ---
    @app.get("/health", tags=["system"])
    async def health_check() -> dict:
        db_healthy = await db_manager.health_check()
        return {
            "status": "healthy" if db_healthy else "degraded",
            "core_version": CORE_VERSION,
            "agent_contract_version": AGENT_CONTRACT_VERSION,
            "environment": settings.environment,
            "components": {
                "database": "healthy" if db_healthy else "unhealthy",
            },
        }

    @app.get("/", tags=["system"])
    async def root() -> dict:
        return {
            "system": "DSRT Core",
            "version": CORE_VERSION,
            "agent_contract": AGENT_CONTRACT_VERSION,
            "sdk": SDK_VERSION,
            "status": "operational",
        }

    # --- Domain routers ---
    app.include_router(auth_router.router)
    app.include_router(capabilities_router.router)
    app.include_router(agents_router.router)
    app.include_router(tasks_router.router)
    app.include_router(executions_router.router)
    app.include_router(events_router.router)
    app.include_router(artifacts_router.router)
    app.include_router(providers_router.router)
    app.include_router(credentials_router.router)

    return app