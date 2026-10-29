"""Unit tests for MVP-POLISH-3 — CLI logging (``orya`` + ``python -m app.db.migrate``)."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.config import clear_settings_cache, get_settings
from app.core.logging_setup import configure_cli_logging


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox config: no inherited ORYA_* env, no repo .env, temp config.yaml.

    ``configure_cli_logging`` reads ``settings.log_level`` through the
    cached ``get_settings()`` — the repo-root ``.env`` must not leak in.
    """
    for name in list(os.environ):
        if name.startswith("ORYA_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)  # ignore any project-root .env
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    yield
    clear_settings_cache()


@pytest.fixture(autouse=True)
def restored_root_level() -> Iterator[None]:
    """The CLI helper mutates the root logger level — put it back afterwards."""
    root = logging.getLogger()
    saved = root.level
    yield
    root.setLevel(saved)


# --- configure_cli_logging ----------------------------------------------


def test_cli_logging_uses_settings_level(monkeypatch: pytest.MonkeyPatch):
    """``ORYA_LOG_LEVEL`` drives the CLI root level (same source as the file logger)."""
    monkeypatch.setenv("ORYA_LOG_LEVEL", "DEBUG")
    clear_settings_cache()
    assert get_settings().log_level == "DEBUG"

    configure_cli_logging()

    assert logging.getLogger().level == logging.DEBUG


def test_cli_logging_defaults_to_info():
    """Without any config the CLI logs at INFO — summaries must be visible."""
    configure_cli_logging()

    assert logging.getLogger().level == logging.INFO


# --- orya import ---------------------------------------------------------


def test_main_import_logs_report(monkeypatch: pytest.MonkeyPatch, caplog):
    """``orya import`` prints its report through the logger (was ``print()``)."""
    from app.core.llm.importers import IMPORTERS, ImportReport

    report = ImportReport(
        source="opencode",
        source_path="/home/dev/.opencode/config.json",
        config_path="/home/dev/.orya/providers.yaml",
        found_providers=["deepseek", "anthropic"],
        default_provider="deepseek",
        default_model="deepseek-chat",
        missing_env_vars=["DEEPSEEK_API_KEY"],
        notes=["note-one"],
    )
    monkeypatch.setitem(IMPORTERS, "opencode", lambda: report)
    monkeypatch.setattr(sys, "argv", ["orya", "import", "--from", "opencode"])

    from app.main import main

    with caplog.at_level(logging.INFO):
        main()

    text = caplog.text
    assert "Imported from opencode (/home/dev/.opencode/config.json)" in text
    assert "Config written:  /home/dev/.orya/providers.yaml" in text
    assert "Providers found: deepseek, anthropic" in text
    assert "Default:         deepseek/deepseek-chat" in text
    assert "Note: note-one" in text
    # Missing env vars are actionable — surfaced as a WARNING, one record.
    assert "Set these env vars" in text
    assert "DEEPSEEK_API_KEY=..." in text
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1


def test_main_import_no_warning_when_env_complete(
    monkeypatch: pytest.MonkeyPatch, caplog
):
    """A fully-configured import logs its report without raising the level."""
    from app.core.llm.importers import IMPORTERS, ImportReport

    report = ImportReport(
        source="continue",
        source_path="/home/dev/.continue/config.yaml",
        config_path="/home/dev/.orya/providers.yaml",
        found_providers=["anthropic"],
        default_provider="anthropic",
        default_model="claude-sonnet-3.5",
    )
    monkeypatch.setitem(IMPORTERS, "continue", lambda: report)
    monkeypatch.setattr(sys, "argv", ["orya", "import", "--from", "continue"])

    from app.main import main

    with caplog.at_level(logging.INFO):
        main()

    assert "Imported from continue" in caplog.text
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


# --- orya db migrate / python -m app.db.migrate ---------------------------


@pytest.mark.parametrize(
    ("applied", "expected"),
    [
        (["0001_init", "0002_x"], "Applied migrations: 0001_init, 0002_x"),
        ([], "No pending migrations."),
    ],
)
def test_main_db_migrate_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog,
    applied: list[str],
    expected: str,
):
    """``orya db migrate`` reports through the logger (was ``print()``)."""
    import app.db

    async def fake_pool():
        return object()

    async def fake_apply(pool):
        return applied

    async def fake_close():
        return None

    monkeypatch.setattr(app.db, "get_asyncpg_pool", fake_pool)
    monkeypatch.setattr(app.db, "apply_migrations", fake_apply)
    monkeypatch.setattr(app.db, "close_pool", fake_close)
    monkeypatch.setattr(sys, "argv", ["orya", "db", "migrate"])

    from app.main import main

    with caplog.at_level(logging.INFO):
        main()

    assert expected in caplog.text


@pytest.mark.parametrize(
    ("applied", "expected"),
    [
        (["0001_init", "0002_x"], "Applied migrations: 0001_init, 0002_x"),
        ([], "No pending migrations."),
    ],
)
def test_module_entry_migrate_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog,
    applied: list[str],
    expected: str,
):
    """``python -m app.db.migrate`` configures logging itself and logs the summary."""
    import app.db
    from app.db import migrate

    async def fake_pool():
        return object()

    async def fake_apply(pool):
        return applied

    async def fake_close():
        return None

    monkeypatch.setattr(app.db, "get_asyncpg_pool", fake_pool)
    monkeypatch.setattr(app.db, "close_pool", fake_close)
    monkeypatch.setattr(migrate, "apply_migrations", fake_apply)

    with caplog.at_level(logging.INFO):
        asyncio.run(migrate._main())

    assert expected in caplog.text
