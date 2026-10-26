"""
DSRT Core API Application Factory.

Mounts all routers from C1–C11. C10 unified execution engine
is instantiated during lifespan and injected into C10 routers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.api.errors import register_error_handlers
from core.config import get_settings
from core.observability.logging import get_logger, setup_logging
from core.observability.middleware import ObservabilityMiddleware
from core.storage.database import db_manager
from core.version import AGENT_CONTRACT_VERSION, CORE_VERSION, SDK_VERSION

# --- C1–C9 routers (static, no dependencies) ---
from core.api.routers import agents as agents_router
from core.api.routers import arena as arena_router
from core.api.routers import artifacts as artifacts_router
from core.api.routers import auth as auth_router
from core.api.routers import capabilities as capabilities_router
from core.api.routers import credentials as credentials_router
from core.api.routers import events as events_router
from core.api.routers import memory as memory_router
from core.api.routers import orchestration as orchestration_router
from core.api.routers import providers as providers_router
from core.api.routers import tasks as tasks_router
from core.api.routers import verification as verification_router
from core.api.routers import worlds as worlds_router

# --- C10 routers (factory — need engine instance) ---
from core.execution.api.executions import build_executions_router
from core.execution.api.experiments import build_experiments_router

# --- C11 router ---
from api.v1.optimization import router as optimization_router


# Production CORS origins — add your Vercel URL here
PRODUCTION_ORIGINS = [
    "https://dsrt.vercel.app",       # ← replace with your actual Vercel project URL
    "https://dsrt-open-arena.vercel.app",
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — startup and shutdown."""
    logger = get_logger("dsrt.core")

    logger.info(
        "dsrt_core_starting",
        core_version=CORE_VERSION,
        agent_contract_version=AGENT_CONTRACT_VERSION,
        sdk_version=SDK_VERSION,
        environment=get_settings().environment,
    )

    # --- Database ---
    await db_manager.initialize()
    db_healthy = await db_manager.health_check()
    if not db_healthy:
        logger.error("database_health_check_failed_on_startup")
        raise RuntimeError(
            "Database is not reachable — cannot start DSRT Core."
        )

    # --- C10 Unified Execution Engine ---
    try:
        from core.execution.integration.unified_engine import UnifiedExecutionEngine
        engine = UnifiedExecutionEngine()
        await engine.initialize()
        app.state.execution_engine = engine
        logger.info("c10_unified_engine_initialized")

        # Mount C10 routers inside lifespan after engine is initialized
        app.include_router(build_executions_router(engine))
        app.include_router(build_experiments_router(engine))
        logger.info("c10_routers_mounted")
    except Exception as e:
        logger.warning(
            "c10_engine_init_failed_running_without_unified_engine",
            error=str(e),
        )
        app.state.execution_engine = None

    logger.info("dsrt_core_ready")

    yield

    logger.info("dsrt_core_shutting_down")

    # Shutdown C10 engine
    engine = getattr(app.state, "execution_engine", None)
    if engine is not None:
        try:
            await engine.shutdown()
        except Exception as e:
            logger.warning("c10_engine_shutdown_error", error=str(e))

    await db_manager.shutdown()


def create_app() -> FastAPI:
    """Create the DSRT Core FastAPI application."""
    settings = get_settings()
    setup_logging()

    app = FastAPI(
        title="DSRT Core",
        description="DSRT Open Arena — Model-Independent Intelligence Execution System",
        version=CORE_VERSION,
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    # --- CORS (production-locked) ---
    if settings.debug:
        allowed_origins = ["*"]
    else:
        allowed_origins = PRODUCTION_ORIGINS

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-Idempotency-Key"],
    )

    app.add_middleware(ObservabilityMiddleware)
    register_error_handlers(app)

    # =================================================================
    # System endpoints
    # =================================================================
    @app.get("/health", tags=["system"])
    async def health_check() -> dict:
        db_healthy = await db_manager.health_check()
        engine = getattr(app.state, "execution_engine", None)
        return {
            "status": "healthy" if db_healthy else "degraded",
            "core_version": CORE_VERSION,
            "agent_contract_version": AGENT_CONTRACT_VERSION,
            "environment": settings.environment,
            "components": {
                "database": "healthy" if db_healthy else "unhealthy",
                "execution_engine": "healthy" if engine else "unavailable",
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

    # =================================================================
    # C1–C9 routers (static)
    # =================================================================
    app.include_router(auth_router.router)
    app.include_router(capabilities_router.router)
    app.include_router(agents_router.router)
    app.include_router(tasks_router.router)
    app.include_router(events_router.router)
    app.include_router(artifacts_router.router)
    app.include_router(providers_router.router)
    app.include_router(credentials_router.router)
    app.include_router(orchestration_router.router)
    app.include_router(verification_router.router)
    app.include_router(memory_router.router)
    app.include_router(worlds_router.router)
    app.include_router(arena_router.router)

    # C1 basic execution CRUD — internal/legacy prefix to avoid collision with C10
    from core.api.routers import executions as c1_executions_router
    c1_executions_router.router.prefix = "/api/v1/internal/executions"
    app.include_router(c1_executions_router.router)

    # =================================================================
    # C11 Adaptive Intelligence & Optimization
    # =================================================================
    app.include_router(optimization_router)

    return app
