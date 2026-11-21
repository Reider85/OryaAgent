"""Boot-path regression tests (start-script launch fixes).

Three regressions each broke a fresh `scripts/start.*` run on HEAD and are
locked here:

* ``selector_loop_factory`` must return a loop **instance** — uvicorn (>=0.36,
  locked at 0.54) passes a custom ``--loop module:attr`` import to
  ``asyncio_run(loop_factory=...)`` untouched, so returning the *class*
  crashed ``make dev``/the start scripts with ``create_task() missing 'coro'``;
* ``app.web.nextjs_ui`` must import (it previously imported the nonexistent
  ``app.core.auth.get_current_user`` / ``app.db.session`` and every startup
  logged "Next.js Web UI (B-11) not available");
* the chainlit app must keep chainlit's auto data layer disabled — with
  ``DATABASE_URL`` exported by the start scripts, chainlit otherwise wrote to
  its missing ``Thread`` table and logged ``relation "Thread" does not exist``
  on every disconnect.
"""

from __future__ import annotations

import asyncio

# --- uvicorn --loop contract ------------------------------------------------


def test_selector_loop_factory_returns_loop_instance() -> None:
    from app.core.loop_factory import selector_loop_factory

    loop = selector_loop_factory()
    assert isinstance(loop, asyncio.AbstractEventLoop)
    assert isinstance(loop, asyncio.SelectorEventLoop)
    loop.close()


def test_uvicorn_custom_loop_import_yields_working_loop() -> None:
    """The exact path uvicorn takes for ``--loop module:attr``."""
    from uvicorn.config import Config

    config = Config(
        app="app.main:app",
        loop="app.core.loop_factory:selector_loop_factory",
    )
    factory = config.get_loop_factory()
    loop = factory()
    assert isinstance(loop, asyncio.AbstractEventLoop)
    loop.close()


# --- Next.js UI module must import -----------------------------------------


def test_nextjs_ui_module_imports() -> None:
    """Import failure turned into a warning on every API start and the
    /web router was never mounted."""
    import app.web.nextjs_ui as nextjs_ui

    assert len(nextjs_ui.router.routes) > 0


# --- chainlit auto data layer stays disabled --------------------------------


def test_chainlit_auto_data_layer_stays_disabled(monkeypatch) -> None:
    """DATABASE_URL in the environment must not reactivate chainlit's own
    persistence (its ``Thread`` table does not exist in this schema)."""
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://orya:orya_password@localhost:5432/orya_sessions"
    )

    import chainlit.data as cl_data

    # Reset chainlit's module singletons so get_data_layer() re-evaluates.
    cl_data._data_layer = None
    cl_data._data_layer_initialized = False

    from chainlit.config import config as cl_config

    import app.ui.chainlit_app  # noqa: F401  — installs the no-op factory

    assert callable(cl_config.code.data_layer), "chainlit_app must register a factory"
    assert cl_data.get_data_layer() is None


# --- `orya db` CLI (the compose api container runs `orya db migrate`) --------


def test_cli_db_migrate_awaits_the_async_migration(monkeypatch, capsys) -> None:
    """`orya db migrate` used to call the async apply_migrations() without
    await — a silent no-op, so a fresh compose database was never schema'd."""
    import sys

    import app.db.migrate as migrate_mod
    import app.main as main_mod

    called: list[str] = []

    async def fake_apply(url=None):
        called.append("apply")
        return ["0001_init"]

    monkeypatch.setattr(migrate_mod, "apply_migrations", fake_apply)
    monkeypatch.setattr(sys, "argv", ["orya", "db", "migrate"])

    main_mod.main()

    assert called == ["apply"]
    assert "0001_init" in capsys.readouterr().out


def test_cli_db_current_prints_the_revision(monkeypatch, capsys) -> None:
    """`orya db current` imported a nonexistent print_current_revision."""
    import sys

    import app.db.migrate as migrate_mod
    import app.main as main_mod

    async def fake_current(url=None):
        return "0002_session_log_encryption"

    monkeypatch.setattr(migrate_mod, "current_revision", fake_current)
    monkeypatch.setattr(sys, "argv", ["orya", "db", "current"])

    main_mod.main()

    assert "0002_session_log_encryption" in capsys.readouterr().out


def test_cli_db_downgrade_uses_the_async_api(monkeypatch, capsys) -> None:
    """`orya db downgrade` imported a nonexistent downgrade_migration."""
    import sys

    import app.db.migrate as migrate_mod
    import app.main as main_mod

    called: list[str] = []

    async def fake_downgrade(revision, url=None):
        called.append(revision)
        return []

    monkeypatch.setattr(migrate_mod, "downgrade", fake_downgrade)
    monkeypatch.setattr(sys, "argv", ["orya", "db", "downgrade", "base"])

    main_mod.main()

    assert called == ["base"]
