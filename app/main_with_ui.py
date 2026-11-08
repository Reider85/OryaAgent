"""Main FastAPI application including UI routes.

Combines all API routes including the new UI components for B-18 to B-21.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.learn import router as learn_router
from app.api.llm import router as llm_router
from app.api.memory import router as memory_router
from app.api.metrics import router as metrics_router
from app.api.middleware import install_middleware
from app.api.sessions import router as sessions_router
from app.api.skills import router as skills_router
from app.api.sqlite_store import router as sqlite_store_router
from app.api.workspace import router as workspace_router
from app.core.logging_setup import (
    configure_cli_logging,
    install_file_logger,
    route_uvicorn_logs_to_root,
)

# Import UI routers
from app.ui.branch_manager_ui import router as branch_manager_ui_router
from app.ui.hooks_ui import router as hooks_ui_router
from app.ui.skills_ui import router as skills_ui_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


def _configured_level() -> int:
    """Numeric log level from ``settings.log_level`` (``LOG_LEVEL``)."""
    from app.core.config import get_settings

    name = str(get_settings().log_level or "INFO").upper()
    return getattr(logging, name, logging.INFO)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Wire the M-21 cache backend, the M-14 projection worker and M-27 compaction.

    ``init_cache`` probes Redis per ``settings.cache_backend`` (``auto``
    falls back to the in-memory backend with a warning) and
    ``close_cache`` releases the client on shutdown. The worker
    soft-fails without PostgreSQL (logged warning, retried on the next
    pass) so ``/health`` and unit tests keep working with no database
    running. The compaction worker sleeps
    ``settings.memory_compact_interval_s`` between passes (0 disables it)
    and never lets a failed pass kill the loop.

    File logging is installed here, not at import time: uvicorn applies
    its own ``dictConfig`` after importing the app, so only a post-startup
    hook can route the ``uvicorn*`` loggers (and their ASGI tracebacks)
    into ``logs/api.log``.

    ``init_rate_limiter`` (A-01) probes Redis only while
    ``ORYA_RATE_LIMIT_ENABLED`` is on — the default off kill-switch keeps
    startup zero-cost. ``init_cost_store`` (A-13) follows the same
    contract behind ``ORYA_COST_ROUTER_ENABLED``. ``init_exporter``
    (A-15) starts the Langfuse OTLP worker only when ``LANGFUSE_HOST``
    and both keys are configured (auto-on; ``ORYA_LANGFUSE_EXPORT_ENABLED=false``
    forces it off); shutdown flushes the queue best-effort.
    ``init_observability_sdk`` (A-16) probes the agent_obs seam and
    logs availability — no workers, nothing to shut down.
    ``pool_health_worker`` (A-20) probes the pooled LLM connections every
    ``LLM_POOL_HEALTH_INTERVAL`` seconds (0 disables it; tests pin 0) and
    shutdown closes every pooled client.
    """
    from app.core.auth.rate_limit import close_rate_limiter, init_rate_limiter
    from app.core.cache import close_cache, init_cache
    from app.core.config import get_settings
    from app.core.cost_tracker import close_cost_store, init_cost_store
    from app.core.llm.connection_pool import (
        get_connection_pool,
        pool_health_worker,
    )
    from app.core.memory.compactor import compaction_worker
    from app.core.observability.langfuse import init_exporter, shutdown_exporter
    from app.core.observability.sdk import init_observability_sdk
    from app.db.session_log import projection_worker

    install_file_logger("api.log", level=_configured_level())
    route_uvicorn_logs_to_root()

    await init_cache()
    await init_rate_limiter()
    await init_cost_store()
    init_exporter()
    init_observability_sdk()
    task = asyncio.create_task(projection_worker())
    interval = get_settings().memory_compact_interval_s
    compact_task: asyncio.Task | None = None
    if interval > 0:
        compact_task = asyncio.create_task(compaction_worker(interval))
    pool = get_connection_pool()
    pool_interval = get_settings().llm_pool_health_interval
    pool_task: asyncio.Task | None = None
    if pool.enabled and pool_interval > 0:
        pool_task = asyncio.create_task(pool_health_worker(pool_interval))
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        if compact_task is not None:
            compact_task.cancel()
            with suppress(asyncio.CancelledError):
                await compact_task
        if pool_task is not None:
            pool_task.cancel()
            with suppress(asyncio.CancelledError):
                await pool_task
            await pool.aclose()
        await close_rate_limiter()
        await close_cost_store()
        await asyncio.to_thread(shutdown_exporter)
        await close_cache()


app = FastAPI(
    title="OryaAgent",
    description="Senior Python coding agent with UI and long-term memory",
    version="7.0.0",
    lifespan=_lifespan,
)

# A-00/A-01: Bearer-JWT auth, rate-limit, CORS, X-Request-ID (outermost last).
install_middleware(app)

# Core API routers
app.include_router(llm_router)
app.include_router(sessions_router)
app.include_router(learn_router)
app.include_router(memory_router)
app.include_router(metrics_router)
app.include_router(skills_router)
app.include_router(workspace_router)
app.include_router(health_router)

# SQLite Store API router
app.include_router(sqlite_store_router)

# UI routers
app.include_router(branch_manager_ui_router)
app.include_router(hooks_ui_router)
app.include_router(skills_ui_router)


def main() -> None:
    """Console entry point (``orya``)."""
    import argparse

    parser = argparse.ArgumentParser(prog="orya", description="OryaAgent CLI")
    parser.add_argument("--host", default="127.0.0.1", help="host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="port to bind to")
    parser.add_argument(
        "--reload", action="store_true", help="auto-reload on code changes"
    )
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
