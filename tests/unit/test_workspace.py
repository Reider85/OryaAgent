"""Unit tests for the per-session workspace seam («open project»)."""

from __future__ import annotations

import os
from importlib import import_module
from pathlib import Path

import pytest
from langchain_core.tools import ToolException

from app.core.workspace import (
    current_workspace,
    open_workspace,
    set_workspace,
    workspace_scope,
)
from app.tools._validators import allowed_roots, validate_path

# ``import app.tools.bash`` would yield the tool object (the package
# re-exports it under the same name), so the module comes from importlib.
bash_module = import_module("app.tools.bash")


@pytest.fixture(autouse=True)
def _reset_workspace():
    """No workspace leaks between tests (ContextVar is per-task)."""
    set_workspace(None)
    yield
    set_workspace(None)


# --- open_workspace ---------------------------------------------------------


def test_open_workspace_resolves_existing_directory(tmp_path: Path):
    assert open_workspace(tmp_path) == tmp_path.resolve()


def test_open_workspace_rejects_missing_path(tmp_path: Path):
    with pytest.raises(ValueError, match="does not exist"):
        open_workspace(tmp_path / "nope")


def test_open_workspace_rejects_a_file(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(ValueError, match="not a directory"):
        open_workspace(target)


# --- binding ----------------------------------------------------------------


def test_current_workspace_defaults_to_process_cwd():
    assert current_workspace() == Path.cwd()


def test_workspace_scope_binds_and_resets(tmp_path: Path):
    with workspace_scope(tmp_path):
        assert current_workspace() == tmp_path
    assert current_workspace() == Path.cwd()


def test_set_workspace_none_falls_back_to_cwd(tmp_path: Path):
    set_workspace(tmp_path)
    set_workspace(None)
    assert current_workspace() == Path.cwd()


# --- tools ------------------------------------------------------------------


def test_allowed_roots_include_the_session_workspace(tmp_path: Path):
    with workspace_scope(tmp_path):
        assert tmp_path.resolve() in allowed_roots()


def test_validate_path_resolves_relative_paths_against_the_workspace(
    tmp_path: Path,
):
    project = tmp_path / "project"
    project.mkdir()
    _outside = tmp_path / "elsewhere"
    _outside.mkdir()

    with workspace_scope(project):
        assert validate_path("src") == (project / "src").resolve()
        # ...and the workspace root itself is allowed
        assert validate_path(".") == project.resolve()


def test_validate_path_outside_the_workspace_still_raises(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()

    with workspace_scope(project):
        with pytest.raises(ToolException, match="outside allowed roots"):
            validate_path(tmp_path.parent / "outside.txt")


async def test_bash_defaults_to_the_session_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    project = tmp_path / "project"
    project.mkdir()
    captured: dict[str, object] = {}

    async def _fake_exec(command, shell, timeout, cwd, env, handle):
        captured["cwd"] = cwd
        return "ok", "", 0, 1.0

    monkeypatch.setattr(bash_module, "_execute_subprocess", _fake_exec)

    with workspace_scope(project):
        await bash_module.bash.ainvoke({"command": "echo hi"})

    assert captured["cwd"] == project
    assert os.path.isdir(captured["cwd"])
