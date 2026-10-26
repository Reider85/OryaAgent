"""Unit tests for the workspace browse API (folder picker backend).

``GET /workspace/browse`` lists subdirectories only, defaults to the
process cwd, caps the listing and reports no parent at a filesystem
root. No infrastructure needed — tmp_path trees only.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.workspace as api_workspace
from app.core.config import clear_settings_cache


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config (the browse handler touches the cwd default)."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {"DATABASE_URL", "LOG_LEVEL"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_browse_route_registered(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/workspace/browse" in paths
    assert "get" in paths["/workspace/browse"]


def test_browse_defaults_to_cwd_and_lists_dirs_only(
    client: TestClient, tmp_path: Path
) -> None:
    (tmp_path / "beta").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / "notes.txt").write_text("irrelevant", encoding="utf-8")

    response = client.get("/workspace/browse")

    assert response.status_code == 200
    data = response.json()
    assert data["path"] == str(tmp_path.resolve())
    assert [entry["name"] for entry in data["dirs"]] == ["alpha", "beta"]
    assert data["truncated"] is False


def test_browse_honours_the_path_query(client: TestClient, tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "src").mkdir(parents=True)

    response = client.get("/workspace/browse", params={"path": str(project)})

    data = response.json()
    assert data["path"] == str(project.resolve())
    assert data["parent"] == str(tmp_path.resolve())
    assert [entry["name"] for entry in data["dirs"]] == ["src"]


def test_browse_missing_path_is_400(client: TestClient, tmp_path: Path) -> None:
    response = client.get("/workspace/browse", params={"path": str(tmp_path / "gone")})

    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"]


def test_browse_a_file_is_400(client: TestClient, tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")

    response = client.get("/workspace/browse", params={"path": str(target)})

    assert response.status_code == 400
    assert "not a directory" in response.json()["detail"]


def test_browse_caps_the_listing(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_workspace, "MAX_DIRS", 2)
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()

    response = client.get("/workspace/browse", params={"path": str(tmp_path)})

    data = response.json()
    assert len(data["dirs"]) == 2
    assert data["truncated"] is True


def test_browse_root_has_no_parent(client: TestClient, tmp_path: Path) -> None:
    """A drive/filesystem root reports parent=null so the UI hides «Up»."""
    root = Path(tmp_path.anchor)

    response = client.get("/workspace/browse", params={"path": str(root)})

    assert response.status_code == 200
    assert response.json()["parent"] is None
