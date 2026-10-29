"""
OryaAgent v7.0 — FastAPI entry point.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api.learn import router as learn_router
from app.api.llm import router as llm_router
from app.api.memory import router as memory_router
from app.api.metrics import router as metrics_router
from app.api.middleware import install_middleware
from app.api.sessions import router as sessions_router
from app.api.workspace import router as workspace_router
from app.core.logging_setup import (
    configure_cli_logging,
    install_file_logger,
    route_uvicorn_logs_to_root,
)

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
    """
    from app.core.cache import close_cache, init_cache
    from app.core.config import get_settings
    from app.core.memory.compactor import compaction_worker
    from app.db.session_log import projection_worker

    install_file_logger("api.log", level=_configured_level())
    route_uvicorn_logs_to_root()

    await init_cache()
    task = asyncio.create_task(projection_worker())
    interval = get_settings().memory_compact_interval_s
    compact_task: asyncio.Task | None = None
    if interval > 0:
        compact_task = asyncio.create_task(compaction_worker(interval))
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
        await close_cache()


app = FastAPI(
    title="OryaAgent",
    description="Senior Python coding agent with UI and long-term memory",
    version="7.0.0",
    lifespan=_lifespan,
)

# A-00: Bearer-JWT enforcement, CORS, X-Request-ID (outermost last).
install_middleware(app)

app.include_router(llm_router)
app.include_router(sessions_router)
app.include_router(learn_router)
app.include_router(memory_router)
app.include_router(metrics_router)
app.include_router(workspace_router)


@app.get("/health")
async def health_check():
    """Health check endpoint for M-00 bootstrap verification."""
    return {"status": "ok", "message": "OryaAgent API is running"}


def main() -> None:
    """Console entry point (``orya``)."""
    import argparse

    parser = argparse.ArgumentParser(prog="orya", description="OryaAgent CLI")
    sub = parser.add_subparsers(dest="command")

    import_parser = sub.add_parser(
        "import", help="Import provider config from another agent"
    )
    import_parser.add_argument(
        "--from",
        dest="source",
        required=True,
        choices=["opencode", "continue", "aider", "cline"],
        help="Source agent to import from",
    )

    db_parser = sub.add_parser("db", help="Database commands")
    db_sub = db_parser.add_subparsers(dest="db_command")
    db_sub.add_parser("migrate", help="Apply pending SQL migrations (M-03)")

    auth_parser = sub.add_parser("auth", help="Auth commands (A-00)")
    auth_sub = auth_parser.add_subparsers(dest="auth_command")
    token_parser = auth_sub.add_parser("token", help="Mint a Bearer JWT for API access")
    token_parser.add_argument(
        "--user", default="dev", help="Token subject (request.state.user_id)"
    )
    token_parser.add_argument(
        "--ttl", type=int, default=None, help="Lifetime in seconds (default: settings)"
    )

    args = parser.parse_args()
    configure_cli_logging()
    if args.command == "import":
        from app.core.llm.importers import IMPORTERS

        report = IMPORTERS[args.source]()
        lines = [
            f"Imported from {report.source} ({report.source_path})",
            f"  Config written:  {report.config_path}",
            f"  Providers found: {', '.join(report.found_providers) or '(none)'}",
        ]
        if report.default_provider:
            lines.append(
                f"  Default:         {report.default_provider}/{report.default_model or '?'}"
            )
        for note in report.notes:
            lines.append(f"  Note: {note}")
        logger.info("\n".join(lines))
        if report.missing_env_vars:
            logger.warning(
                "Set these env vars to activate providers: %s",
                "; ".join(f"{var}=..." for var in report.missing_env_vars),
            )
    elif args.command == "db" and args.db_command == "migrate":
        import asyncio

        from app.db import apply_migrations, close_pool, get_asyncpg_pool

        async def _run_migrations() -> list[str]:
            pool = await get_asyncpg_pool()
            try:
                return await apply_migrations(pool)
            finally:
                await close_pool()

        applied = asyncio.run(_run_migrations())
        if applied:
            logger.info("Applied migrations: %s", ", ".join(applied))
        else:
            logger.info("No pending migrations.")
    elif args.command == "auth" and args.auth_command == "token":
        from app.core.auth import AuthError, create_token

        try:
            token = create_token(args.user, ttl_s=args.ttl)
        except AuthError as exc:
            logger.error("Cannot mint token: %s", exc)
            raise SystemExit(1) from exc
        print(token)  # stdout carries the artifact (logs carry diagnostics)
    else:
        parser.print_help()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
