"""
OryaAgent v7.0 — FastAPI entry point.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from app.api.llm import router as llm_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Start the M-14 session-log projection worker; cancel it on shutdown.

    The worker soft-fails without PostgreSQL (logged warning, retried on
    the next pass) so ``/health`` and unit tests keep working with no
    database running.
    """
    from app.db.session_log import projection_worker

    task = asyncio.create_task(projection_worker())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="OryaAgent",
    description="Senior Python coding agent with UI and long-term memory",
    version="7.0.0",
    lifespan=_lifespan,
)

app.include_router(llm_router)


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
        choices=["opencode", "continue", "aider"],
        help="Source agent to import from",
    )

    db_parser = sub.add_parser("db", help="Database commands")
    db_sub = db_parser.add_subparsers(dest="db_command")
    db_sub.add_parser("migrate", help="Apply pending SQL migrations (M-03)")

    args = parser.parse_args()
    if args.command == "import":
        from app.core.llm.importers import IMPORTERS

        report = IMPORTERS[args.source]()
        print(f"Imported from {report.source} ({report.source_path})")
        print(f"  Config written:  {report.config_path}")
        print(f"  Providers found: {', '.join(report.found_providers) or '(none)'}")
        if report.default_provider:
            print(
                f"  Default:         {report.default_provider}/{report.default_model or '?'}"
            )
        if report.missing_env_vars:
            print("  Set these env vars to activate providers:")
            for var in report.missing_env_vars:
                print(f"    export {var}=...")
        for note in report.notes:
            print(f"  Note: {note}")
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
            print(f"Applied migrations: {', '.join(applied)}")
        else:
            print("No pending migrations.")
    else:
        parser.print_help()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
