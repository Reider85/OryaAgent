"""Unit tests for M-26 — /learn endpoints (BACKLOG6 M-26 + PROMPT_MVP §3.7).

No infra: the projection refresh is stubbed, the session log is a JSONL
fixture written straight into ``ORYA_SESSIONS_DIR`` and the L0 store lives
in ``tmp_path``. Covers the AC trace: capture + auto-name, 400s, the
``learn`` audit record, concurrency, compaction flag, the PROMPT_MVP
content contract and the prompt-visibility requirement.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import app.api.learn as api_learn
from app.api.learn import LearnRequest
from app.core.config import clear_settings_cache
from app.core.memory import drain_memory_audits, parse_entries
from app.core.prompt import format_memory_block

_TS = "2026-01-01T00:00:00+00:00"


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Sandbox env/config, point the memory/session dirs at tmp_path."""
    for name in list(os.environ):
        if name.startswith("ORYA_") or name in {"DATABASE_URL", "LOG_LEVEL"}:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORYA_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("ORYA_SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("ORYA_MEMORY_DIR", str(tmp_path / "memory"))
    clear_settings_cache()

    async def _no_refresh(session_id: str) -> int:
        return 0

    monkeypatch.setattr(api_learn, "project_thread", _no_refresh)
    yield
    clear_settings_cache()


# --- fixtures -----------------------------------------------------------------


def _write_log(session_id: str, events: list[dict]) -> Path:
    path = Path(os.environ["ORYA_SESSIONS_DIR"]) / f"{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events), encoding="utf-8"
    )
    return path


def _turn(steps: list[dict]) -> list[dict]:
    """Projected turn: user → ai(tool_calls) → tool results → final ai."""
    events: list[dict] = [
        {"ts": _TS, "type": "user", "payload": {"message_id": "m1", "content": "go"}}
    ]
    calls = [
        {
            "name": step["name"],
            "args": step.get("args", {}),
            "id": f"c{index}",
        }
        for index, step in enumerate(steps)
    ]
    if calls:
        events.append(
            {
                "ts": _TS,
                "type": "ai",
                "payload": {"message_id": "m2", "content": "", "tool_calls": calls},
            }
        )
    for index, step in enumerate(steps):
        payload: dict[str, Any] = {
            "message_id": f"t{index}",
            "content": step.get("content", "ok"),
            "tool_call_id": f"c{index}",
            "name": step["name"],
            "status": step.get("status", "success"),
        }
        events.append({"ts": _TS, "type": "tool", "payload": payload})
    events.append(
        {"ts": _TS, "type": "ai", "payload": {"message_id": "m9", "content": "done"}}
    )
    return events


def _memory_file(name: str) -> str:
    return (Path(os.environ["ORYA_MEMORY_DIR"]) / name).read_text(encoding="utf-8")


def _bash_result(exit_code: int) -> str:
    body = json.dumps(
        {"stdout": "", "stderr": "", "exit_code": exit_code, "truncated": False}
    )
    return f"[UNTRUSTED_CONTENT_START]\n{body}\n[UNTRUSTED_CONTENT_END]"


# --- router registration ------------------------------------------------------


def test_learn_routes_registered(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "post" in paths["/sessions/{session_id}/learn"]
    assert "post" in paths["/learn"]


# --- POST /sessions/{id}/learn ------------------------------------------------


def test_learn_captures_successful_sequence(client: TestClient) -> None:
    _write_log(
        "s-1",
        _turn(
            [
                {"name": "grep", "args": {"pattern": "def foo"}},
                {"name": "read", "args": {"path": "app/x.py"}},
                {"name": "edit", "args": {"path": "app/x.py"}},
            ]
        ),
    )

    response = client.post("/sessions/s-1/learn", json={})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["learned_id"] == "learn_001"
    assert data["file"] == "LEARNED.md"
    assert data["compacted"] is False
    assert data["line_count"] >= 1

    content = _memory_file("LEARNED.md")
    assert "- [learned] id=learn_001" in content
    assert "confidence=0.9 |" in content
    assert "source=/learn" in content
    assert "«grep_read_edit»" in content  # auto-name as scenario fallback
    assert (
        "`grep(pattern=def foo)` → `read(path=app/x.py)` → `edit(path=app/x.py)`"
        in (content)
    )
    entries = parse_entries(content, default_kind="learned")
    assert entries and entries[0].id == "learn_001"
    assert entries[0].kind == "learned"


def test_learn_accepts_pattern_name_and_description(client: TestClient) -> None:
    _write_log("s-1", _turn([{"name": "grep"}]))

    response = client.post(
        "/sessions/s-1/learn",
        json={
            "pattern_name": "refactor_extract",
            "description": "Refactor: extract function",
        },
    )

    assert response.status_code == 200
    assert response.json()["learned_id"] == "learn_001"
    content = _memory_file("LEARNED.md")
    assert "«Refactor: extract function»" in content
    assert "name: refactor_extract" in content


def test_learn_is_scoped_to_the_last_turn(client: TestClient) -> None:
    events = _turn([{"name": "grep"}])
    events += _turn([{"name": "read"}])
    _write_log("s-1", events)

    response = client.post("/sessions/s-1/learn", json={})

    assert response.status_code == 200
    content = _memory_file("LEARNED.md")
    assert "`read`" in content
    assert "`grep`" not in content


def test_learn_last_tool_error_is_400(client: TestClient) -> None:
    _write_log(
        "s-1",
        _turn(
            [
                {"name": "grep"},
                {"name": "edit", "status": "error", "content": "conflict"},
            ]
        ),
    )

    response = client.post("/sessions/s-1/learn", json={})

    assert response.status_code == 400
    assert response.json()["detail"] == "No successful tool-call sequence to learn"


def test_learn_error_before_success_captures_last_run(client: TestClient) -> None:
    _write_log(
        "s-1",
        _turn(
            [
                {"name": "grep", "status": "error", "content": "no matches"},
                {"name": "read"},
            ]
        ),
    )

    response = client.post("/sessions/s-1/learn", json={})

    assert response.status_code == 200
    content = _memory_file("LEARNED.md")
    assert "`read`" in content
    assert "`grep`" not in content


def test_learn_denied_tool_is_400(client: TestClient) -> None:
    _write_log(
        "s-1",
        _turn(
            [{"name": "write", "content": "Denied by policy: outside allowed roots"}]
        ),
    )

    assert client.post("/sessions/s-1/learn", json={}).status_code == 400


def test_learn_bash_nonzero_exit_is_400(client: TestClient) -> None:
    _write_log("s-1", _turn([{"name": "bash", "content": _bash_result(2)}]))

    assert client.post("/sessions/s-1/learn", json={}).status_code == 400


def test_learn_bash_zero_exit_is_captured(client: TestClient) -> None:
    _write_log("s-1", _turn([{"name": "bash", "content": _bash_result(0)}]))

    response = client.post("/sessions/s-1/learn", json={})

    assert response.status_code == 200
    assert "`bash`" in _memory_file("LEARNED.md")


def test_learn_without_status_field_falls_back_to_content(client: TestClient) -> None:
    """Old projections carry no ``status`` — the heuristics still decide."""
    events = _turn([{"name": "grep"}])
    for event in events:
        if event["type"] == "tool":
            event["payload"].pop("status", None)
    _write_log("s-1", events)

    assert client.post("/sessions/s-1/learn", json={}).status_code == 200


def test_learn_without_tool_calls_is_400(client: TestClient) -> None:
    _write_log("s-1", _turn([]))

    response = client.post("/sessions/s-1/learn", json={})

    assert response.status_code == 400
    assert "No successful tool-call sequence" in response.json()["detail"]


def test_learn_without_a_log_is_400(client: TestClient) -> None:
    response = client.post("/sessions/nope/learn", json={})

    assert response.status_code == 400


def test_learn_survives_a_failed_projection_refresh(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(session_id: str) -> int:
        raise RuntimeError("postgres down")

    monkeypatch.setattr(api_learn, "project_thread", _boom)
    _write_log("s-1", _turn([{"name": "grep"}]))

    assert client.post("/sessions/s-1/learn", json={}).status_code == 200


def test_learn_rejects_an_unknown_scope(client: TestClient) -> None:
    _write_log("s-1", _turn([{"name": "grep"}]))

    response = client.post("/sessions/s-1/learn", json={"scope": "galaxy"})

    assert response.status_code == 422


def test_learn_reports_compaction_over_budget(client: TestClient) -> None:
    memory = Path(os.environ["ORYA_MEMORY_DIR"])
    memory.mkdir(parents=True, exist_ok=True)
    (memory / "LEARNED.md").write_text("z" * 4200 + "\n", encoding="utf-8")
    _write_log("s-1", _turn([{"name": "grep"}]))

    response = client.post("/sessions/s-1/learn", json={})

    assert response.status_code == 200
    assert response.json()["compacted"] is True
    assert "id=learn_001" in _memory_file("LEARNED.md")


def test_two_sessions_learn_without_lost_updates(client: TestClient) -> None:
    _write_log("s-1", _turn([{"name": "grep"}]))
    _write_log("s-2", _turn([{"name": "read"}]))

    first = client.post("/sessions/s-1/learn", json={})
    second = client.post("/sessions/s-2/learn", json={})

    assert [first.json()["learned_id"], second.json()["learned_id"]] == [
        "learn_001",
        "learn_002",
    ]
    content = _memory_file("LEARNED.md")
    assert "`grep`" in content and "`read`" in content


def test_concurrent_learn_keeps_both_entries() -> None:
    """Two writers race on ``next_id`` — the lock yields 001 and 002."""
    results: list[api_learn.LearnResponse] = []
    barrier = threading.Barrier(2)

    def _worker(index: int) -> None:
        barrier.wait()
        results.append(
            api_learn._store_entry(
                "LEARNED.md",
                f"entry {index}",
                kind="learned",
                confidence=0.9,
                source="/learn",
                session_id=f"s-{index}",
                reason="/learn",
            )
        )

    threads = [threading.Thread(target=_worker, args=(i,)) for i in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(response.learned_id for response in results) == [
        "learn_001",
        "learn_002",
    ]
    content = _memory_file("LEARNED.md")
    assert "entry 1" in content and "entry 2" in content


# --- audit (AC: op=learn, file, memory_id, source, trace_id) ------------------


async def test_learn_records_memory_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.db.get_pool_if_created", lambda: None)
    _write_log("s-1", _turn([{"name": "grep"}]))

    await api_learn.learn_session("s-1", LearnRequest())
    await drain_memory_audits()

    trail = Path(os.environ["ORYA_MEMORY_DIR"]) / "audit" / "memory_audit.jsonl"
    records = [
        json.loads(line) for line in trail.read_text(encoding="utf-8").splitlines()
    ]
    learn = next(record for record in records if record["action"] == "learn")
    assert learn["file"] == "LEARNED.md"
    assert learn["memory_id"] == "learn_001"
    assert learn["source"] == "/learn"
    assert learn["trace_id"]
    # the PG row keeps the same triple folded into ``reason`` (no migration)
    assert "memory_id=learn_001" in learn["reason"]
    assert "source=/learn" in learn["reason"]
    assert "trace_id=" in learn["reason"]
    # the M-25 append row is still written alongside it
    assert any(record["action"] == "memory.append" for record in records)


# --- POST /learn (PROMPT_MVP content contract) --------------------------------


@pytest.mark.parametrize(
    ("category", "file", "learned_id"),
    [
        ("fact", "FACTS.md", "fact_001"),
        ("preference", "PREFERENCES.md", "pref_001"),
        ("project", "LEARNED.md", "learn_001"),
    ],
)
def test_content_endpoint_maps_category(
    client: TestClient, category: str, file: str, learned_id: str
) -> None:
    response = client.post(
        "/learn", json={"content": "Project uses PostgreSQL 16", "category": category}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["file"] == file
    assert data["learned_id"] == learned_id
    content = _memory_file(file)
    assert f"id={learned_id}" in content
    assert "Project uses PostgreSQL 16" in content


def test_content_endpoint_defaults_to_fact(client: TestClient) -> None:
    response = client.post("/learn", json={"content": "rg is required"})

    assert response.status_code == 200
    assert response.json()["file"] == "FACTS.md"


@pytest.mark.parametrize(
    "body", [{"content": ""}, {"content": "x", "category": "todo"}, {}]
)
def test_content_endpoint_validation(client: TestClient, body: dict) -> None:
    assert client.post("/learn", json=body).status_code == 422


# --- prompt visibility (PROMPT_MVP: /learn я виден на следующем turn) ----------


def test_learned_entry_is_visible_to_the_prompt(client: TestClient) -> None:
    _write_log("s-1", _turn([{"name": "grep"}]))

    client.post("/sessions/s-1/learn", json={"description": "remember this"})

    block = format_memory_block()
    assert "id=learn_001" in block
    assert "remember this" in block
