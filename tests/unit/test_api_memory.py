"""Unit tests for M-27 — /memory endpoints (PROMPT_MVP §3.7 + BACKLOG6 M-27).

No infra: the L0 store lives in ``tmp_path`` (``ORYA_MEMORY_DIR``) and the
session-scoped path variants share their handlers with the global ones (the
union contract). Covers the AC trace: compact results per file, stats shape
from both specs, the markdown ``/memory`` cat and ``last_compacted``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import clear_settings_cache
from app.core.memory import FILES, MDStore, drain_memory_audits
from app.core.memory.models import MemoryItem

_LEARNED_BUDGET = MDStore.MAX_BYTES["LEARNED.md"]


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config, point the memory dir at tmp_path."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {"DATABASE_URL", "LOG_LEVEL"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("ORYA_MEMORY_DIR", str(tmp_path / "memory"))
    clear_settings_cache()
    yield
    clear_settings_cache()


def _learned(text: str, *, confidence: float = 1.0) -> str:
    return MemoryItem.create(
        kind="learned", text=text, confidence=confidence, source="/learn"
    ).to_markdown()


def _fill_store(file: str, blocks: list[str]) -> Path:
    path = Path(os.environ["ORYA_MEMORY_DIR"]) / file
    path.parent.mkdir(parents=True, exist_ok=True)
    # bytes on purpose: the production write path is binary (no CRLF translation)
    body = "\n\n".join(block.strip("\n") for block in blocks) + "\n"
    path.write_bytes(body.encode("utf-8"))
    return path


# --- routes -------------------------------------------------------------------


def test_memory_routes_registered(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in (
        "/memory/compact",
        "/memory/stats",
        "/memory",
        "/sessions/{session_id}/memory/compact",
        "/sessions/{session_id}/memory/stats",
        "/sessions/{session_id}/memory",
    ):
        assert path in paths, f"{path} missing from the API (M-27 union contract)"
    assert "post" in paths["/memory/compact"]
    assert "get" in paths["/memory/stats"]
    assert "get" in paths["/memory"]


# --- GET /memory/stats ---------------------------------------------------------


def test_stats_reports_both_spec_shapes(client: TestClient) -> None:
    _fill_store("LEARNED.md", [_learned("one"), _learned("two")])

    payload = client.get("/memory/stats").json()

    assert {entry["name"] for entry in payload["files"]} == set(FILES)
    learned = next(e for e in payload["files"] if e["name"] == "LEARNED.md")
    content = Path(os.environ["ORYA_MEMORY_DIR"], "LEARNED.md").read_text(
        encoding="utf-8"
    )
    # BACKLOG6 fields
    assert learned["size_bytes"] == len(content.encode("utf-8"))
    assert learned["entries_count"] == 2
    assert learned["last_write_ts"].endswith("Z")
    # PROMPT_MVP fields
    assert learned["line_count"] == len(content.splitlines())
    assert learned["token_count"] == len(content) // 4
    assert payload["line_counts"]["LEARNED.md"] == learned["line_count"]
    assert payload["token_counts"]["LEARNED.md"] == learned["token_count"]
    assert payload["total_size_bytes"] == sum(
        entry["size_bytes"] for entry in payload["files"]
    )
    assert payload["last_compacted"] is None
    assert learned["max_bytes"] == _LEARNED_BUDGET
    assert learned["over_limit"] is False


def test_stats_last_compacted_follows_a_compaction(client: TestClient) -> None:
    assert client.get("/memory/stats").json()["last_compacted"] is None

    client.post("/memory/compact")

    payload = client.get("/memory/stats").json()
    assert payload["last_compacted"] is None  # nothing was archived yet

    _fill_store(
        "LEARNED.md",
        [_learned("low", confidence=0.4)]
        + [_learned(f"pad {index}") for index in range(11)],
    )
    client.post("/memory/compact")

    payload = client.get("/memory/stats").json()
    assert payload["last_compacted"] and payload["last_compacted"].endswith("Z")


# --- POST /memory/compact -------------------------------------------------------


def test_compact_returns_a_result_per_file(client: TestClient) -> None:
    _fill_store(
        "LEARNED.md",
        [_learned("old " + "x" * 250, confidence=0.4)]
        + [_learned(f"recent {index} " + "x" * 250) for index in range(20)],
    )

    response = client.post("/memory/compact")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert [result["file"] for result in payload["results"]] == [
        "PREFERENCES.md",
        "LEARNED.md",
        "FACTS.md",
        "DECISIONS.md",
    ]
    learned = next(
        result for result in payload["results"] if result["file"] == "LEARNED.md"
    )
    assert learned["changed"] is True
    assert learned["archived"] >= 1
    assert learned["after_bytes"] <= _LEARNED_BUDGET
    assert learned["over_limit"] is False
    assert Path(learned["archive_path"]).is_file()
    assert payload["total_archived"] == sum(
        result["archived"] for result in payload["results"]
    )
    assert payload["total_archived"] == learned["archived"]


def test_compact_of_an_empty_store_changes_nothing(client: TestClient) -> None:
    payload = client.post("/memory/compact").json()

    assert payload["total_archived"] == 0
    assert all(result["changed"] is False for result in payload["results"])
    assert all(result["archive_path"] is None for result in payload["results"])


async def test_compact_is_audited_without_a_pool(client, monkeypatch) -> None:
    monkeypatch.setattr("app.db.get_pool_if_created", lambda: None)
    _fill_store(
        "FACTS.md",
        [
            "- [fact] id=fact_001 | confidence=0.5"
            " | source=/learn | ts=2026-01-01T00:00:00Z"
            "\n  weak"
        ],
    )

    client.post("/memory/compact")
    await drain_memory_audits()

    trail = Path(os.environ["ORYA_MEMORY_DIR"]) / "audit" / "memory_audit.jsonl"
    actions = [
        json.loads(line)["action"]
        for line in trail.read_text(encoding="utf-8").splitlines()
    ]
    assert "memory.compact" in actions


# --- GET /memory (cat) ----------------------------------------------------------


def test_memory_cat_returns_four_files_as_markdown(client: TestClient) -> None:
    _fill_store("LEARNED.md", [_learned("the learned fact")])
    _fill_store("FACTS.md", ["PostgreSQL 16"])

    payload = client.get("/memory").json()

    assert set(payload["files"]) == {
        "LEARNED.md",
        "PREFERENCES.md",
        "FACTS.md",
        "DECISIONS.md",
    }
    assert payload["files"]["LEARNED.md"].startswith("- [learned]")
    assert payload["files"]["FACTS.md"] == "PostgreSQL 16\n"
    assert payload["files"]["PREFERENCES.md"] == ""
    assert payload["markdown"].startswith("# Long-term Memory")
    assert "## LEARNED.md" in payload["markdown"]
    assert "the learned fact" in payload["markdown"]
    assert "(empty)" in payload["markdown"], "blank files render a placeholder"


# --- session-scoped twins -------------------------------------------------------


def test_session_scoped_paths_share_the_global_handlers(client: TestClient) -> None:
    _fill_store("LEARNED.md", [_learned("scoped")])

    stats = client.get("/sessions/sess-1/memory/stats")
    content = client.get("/sessions/sess-1/memory")
    compact = client.post("/sessions/sess-1/memory/compact")

    assert stats.status_code == content.status_code == compact.status_code == 200
    assert stats.json()["files"] == client.get("/memory/stats").json()["files"]
    assert content.json()["markdown"] == client.get("/memory").json()["markdown"]
    assert [r["file"] for r in compact.json()["results"]] == [
        r["file"] for r in client.post("/memory/compact").json()["results"]
    ]
