"""Compactor tests (M-27) — AC trace from BACKLOG6 M-27 + ARCHITECT6 §4.2.2.

Covers the four strategies, the archive-first crash ordering, the atomic
rewrite, the periodic worker (mocked clock), the audit trail, the
``compaction.json`` state and the deliberate \"protected entries\" deviation.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from datetime import UTC, datetime

import pytest

from app.core.memory import MDStore, drain_memory_audits
from app.core.memory import compactor as compactor_module
from app.core.memory.compactor import (
    STRATEGIES,
    Compactor,
    compaction_worker,
    get_compactor,
    read_last_compacted,
)
from app.core.memory.models import MemoryItem

_DAY = datetime.now(UTC).strftime("%Y%m%d")


@pytest.fixture
def store(tmp_path) -> MDStore:
    return MDStore(tmp_path / "memory")


@pytest.fixture
def compactor(store) -> Compactor:
    return Compactor(store)


def _entry(
    kind: str,
    text: str,
    *,
    confidence: float = 1.0,
    source: str = "user_explicit",
) -> str:
    """One record in the ARCHITECT6 §3.1.1 block format."""
    return MemoryItem.create(
        kind=kind, text=text, confidence=confidence, source=source
    ).to_markdown()


def _fill(store: MDStore, file: str, blocks: list[str]) -> None:
    """Write blocks straight to the file (no append hook — we test compaction)."""
    body = "\n\n".join(block.strip("\n") for block in blocks) + "\n"
    (store.memory_dir / file).write_bytes(body.encode("utf-8"))


def _learned(text: str, *, confidence: float = 1.0) -> str:
    return _entry("learned", text, confidence=confidence, source="/learn")


# --- strategies ---------------------------------------------------------------


def test_preferences_archives_only_low_confidence_inferred(compactor):
    blocks = [
        _entry("preference", "tabs", source="user_explicit", confidence=0.5),
        _entry("preference", "inferred-low", source="agent_inferred", confidence=0.5),
        _entry("preference", "inferred-high", source="agent_inferred", confidence=0.9),
        "hand-written note without a meta line",
    ]

    keep, archive = compactor._partition("PREFERENCES.md", blocks)

    assert keep == [0, 2, 3]
    assert archive == [1]


def test_facts_archive_everything_below_nine(compactor):
    blocks = [
        _entry("fact", "weak", confidence=0.8),
        _entry("fact", "strong", confidence=0.9),
        "free text counts as 1.0",
    ]

    keep, archive = compactor._partition("FACTS.md", blocks)

    assert keep == [1, 2]
    assert archive == [0]


def test_decisions_archive_superseded_markers(compactor):
    blocks = [
        "- [decision] id=dec_001 | confidence=1.0 | source=user_explicit"
        " | ts=2026-01-01T00:00:00Z\n  Use REST.\n  superseded_by=dec_002",
        "- [decision] id=dec_002 | confidence=1.0 | source=user_explicit"
        " | ts=2026-01-02T00:00:00Z\n  Use gRPC.",
        "Decision: [superseded] old consensus",
        "Decision: plain, still current",
    ]

    keep, archive = compactor._partition("DECISIONS.md", blocks)

    assert keep == [1, 3]
    assert archive == [0, 2]


def test_learned_keeps_recent_plus_high_confidence(compactor):
    blocks = [_learned(f"old {index}", confidence=0.5) for index in range(3)]
    blocks += [_learned(f"recent {index}") for index in range(12)]

    keep, archive = compactor._partition("LEARNED.md", blocks)

    # entries 0..2 are old AND low-confidence -> archived; 3..14 are recent
    assert archive == [0, 1, 2]
    assert keep == list(range(3, 15))


def test_section_headers_are_never_archived(compactor):
    blocks = ["# My patterns"]
    blocks.append(_learned("old low-confidence", confidence=0.5))
    blocks += [_learned(f"recent {index}") for index in range(10)]

    keep, archive = compactor._partition("LEARNED.md", blocks)

    assert keep[0] == 0, "the header stays"
    assert 1 not in keep
    assert archive == [1]


# --- AC: compaction keeps LEARNED.md within its budget ------------------------


async def test_twenty_entries_compact_under_the_budget(store, compactor):
    """AC: >4 KB LEARNED.md compacts to <=4 KB and the archive holds the rest."""
    blocks = [
        _learned(f"pattern {index}: " + "x" * 250, confidence=0.95)
        for index in range(20)
    ]
    _fill(store, "LEARNED.md", blocks)
    assert store.needs_compaction("LEARNED.md")

    result = await compactor.compact("LEARNED.md")

    assert result.changed is True
    assert result.archived > 0
    assert result.kept + result.archived == 20
    assert result.after_bytes <= MDStore.MAX_BYTES["LEARNED.md"]
    assert not store.needs_compaction("LEARNED.md")

    content = store.read("LEARNED.md")
    assert "pattern 19:" in content, "the newest entry survives"
    assert "pattern 0:" not in content

    archive = store.memory_dir / "archive" / f"LEARNED_{_DAY}.md"
    archived = archive.read_text(encoding="utf-8")
    assert "pattern 0:" in archived
    assert archived.count("- [learned]") == result.archived


async def test_compaction_is_append_only_across_runs(store, compactor):
    def _run(marker: str) -> list[str]:
        # 12 entries: the low-confidence first one is outside the last-10 window
        return [_learned(marker, confidence=0.2)] + [
            _learned(f"pad {index}") for index in range(11)
        ]

    _fill(store, "LEARNED.md", _run("first old entry"))
    await compactor.compact("LEARNED.md")
    _fill(store, "LEARNED.md", _run("second old entry"))
    await compactor.compact("LEARNED.md")

    archive = store.memory_dir / "archive" / f"LEARNED_{_DAY}.md"
    archived = archive.read_text(encoding="utf-8")
    assert "first old entry" in archived
    assert "second old entry" in archived


async def test_protected_entries_survive_an_over_budget_file(compactor, store):
    """Deviation: PREFERENCES/FACTS never size-trim their protected class."""
    blocks = [
        _entry("preference", f"pref {index} " + "y" * 120, source="user_explicit")
        for index in range(30)
    ]
    _fill(store, "PREFERENCES.md", blocks)
    assert store.needs_compaction("PREFERENCES.md")

    result = await compactor.compact("PREFERENCES.md")

    assert result.changed is False
    assert result.over_limit is True
    assert store.read("PREFERENCES.md").count("- [preference]") == 30


async def test_headers_and_free_text_survive_compaction(store, compactor):
    blocks = [
        "# Learned patterns",
        "hand-written context line",
        _learned("low-confidence-marker", confidence=0.5),
    ]
    blocks += [_learned(f"recent {index}") for index in range(10)]
    _fill(store, "LEARNED.md", blocks)

    result = await compactor.compact("LEARNED.md")

    content = store.read("LEARNED.md")
    assert "# Learned patterns" in content
    assert "hand-written context line" in content
    assert "low-confidence-marker" not in content, "the strategy archived it"
    assert result.archived == 1
    archive = store.memory_dir / "archive" / f"LEARNED_{_DAY}.md"
    assert "low-confidence-marker" in archive.read_text(encoding="utf-8")


# --- crash safety --------------------------------------------------------------


def test_crash_mid_rewrite_keeps_the_old_file(store, monkeypatch):
    store.append("LEARNED.md", "old body")

    def boom(source: str, target: str) -> None:
        raise OSError("power loss")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        store.rewrite("LEARNED.md", lambda old: "new body")

    assert store.read("LEARNED.md") == "old body\n\n"
    assert list(store.memory_dir.glob(".*tmp*")) == []


async def test_archive_lands_before_the_rewrite(store, compactor, monkeypatch):
    """AC: a crash between archive and rewrite loses nothing — only duplicates."""
    _fill(
        store,
        "LEARNED.md",
        [_learned(f"entry {index} " + "z" * 250) for index in range(20)],
    )
    before = store.read("LEARNED.md")
    real_replace = os.replace
    failing = {"fail": True}

    def flaky(source: str, target: str) -> None:
        if failing["fail"]:
            raise OSError("crash before replace")
        return real_replace(source, target)

    monkeypatch.setattr(os, "replace", flaky)

    with pytest.raises(OSError):
        await compactor.compact("LEARNED.md")

    assert store.read("LEARNED.md") == before, "the L0 file is untouched"
    archive = store.memory_dir / "archive" / f"LEARNED_{_DAY}.md"
    assert archive.read_text(encoding="utf-8").strip(), "the archive already has them"

    failing["fail"] = False
    result = await compactor.compact("LEARNED.md")

    assert result.changed is True
    assert not store.needs_compaction("LEARNED.md")
    assert store.read("LEARNED.md").count("- [learned]") == result.kept


async def test_append_during_compaction_is_never_lost(store, compactor, monkeypatch):
    """The read-modify-write holds the per-file lock: no lost updates (M-25 AC)."""
    _fill(
        store,
        "LEARNED.md",
        [_learned(f"entry {index} " + "z" * 250) for index in range(20)],
    )
    entered = threading.Event()
    real_append_archive = compactor._append_archive

    def slow_append(file: str, blocks: list[str]):
        entered.set()
        time.sleep(0.1)
        return real_append_archive(file, blocks)

    monkeypatch.setattr(compactor, "_append_archive", slow_append)

    task = asyncio.create_task(compactor.compact("LEARNED.md"))
    while not entered.is_set():
        await asyncio.sleep(0.001)

    store.append("LEARNED.md", _learned("late arrival"))
    await task

    assert "late arrival" in store.read("LEARNED.md")

    deadline = time.monotonic() + 5
    while store._pending and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


# --- periodic worker (AC: mock clock, 24 h) -----------------------------------


async def test_worker_waits_an_interval_and_then_compacts(monkeypatch, tmp_path):
    store = MDStore(tmp_path / "memory")
    _fill(
        store,
        "LEARNED.md",
        [_learned(f"entry {index} " + "z" * 250) for index in range(20)],
    )
    compactor = Compactor(store)
    monkeypatch.setattr(compactor_module, "get_compactor", lambda *a, **k: compactor)

    sleeps: list[float] = []

    async def fake_sleep(interval: float) -> None:
        sleeps.append(interval)
        if len(sleeps) > 1:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await compaction_worker(86400, sleep=fake_sleep)

    assert sleeps == [86400, 86400], "the pass runs after every 24 hours"
    assert not store.needs_compaction("LEARNED.md"), "the pass compacted the file"


async def test_worker_disabled_with_a_zero_interval() -> None:
    await asyncio.wait_for(compaction_worker(0), timeout=1)


async def test_worker_survives_a_failing_pass(monkeypatch, tmp_path):
    monkeypatch.setattr(compactor_module, "get_compactor", lambda *a, **k: _Boom())

    sleeps: list[float] = []

    async def fake_sleep(interval: float) -> None:
        sleeps.append(interval)
        if len(sleeps) > 2:
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await compaction_worker(1, sleep=fake_sleep)

    assert len(sleeps) == 3, "the loop kept sleeping after the failure"


class _Boom:
    async def compact_all_if_needed(self, **kwargs):
        raise RuntimeError("disk on fire")


# --- state, audit, seams -------------------------------------------------------


async def test_compact_all_covers_four_files_and_stamps_state(store, compactor):
    _fill(
        store,
        "DECISIONS.md",
        [
            "- [decision] id=dec_001 | confidence=1.0"
            " | source=user_explicit | ts=2026-01-01T00:00:00Z"
            "\n  old\n  superseded_by=dec_002"
        ],
    )

    results = await compactor.compact_all()

    assert list(results) == list(STRATEGIES)
    assert results["DECISIONS.md"].archived == 1
    state = read_last_compacted(store.memory_dir)
    assert set(state) <= set(STRATEGIES)
    assert "DECISIONS.md" in state
    assert state["DECISIONS.md"].endswith("Z")
    assert (store.memory_dir / "compaction.json").is_file()


async def test_compact_writes_the_audit_record(store, compactor, monkeypatch):
    monkeypatch.setattr("app.db.get_pool_if_created", lambda: None)
    _fill(
        store,
        "LEARNED.md",
        [_learned("old fact", confidence=0.5)]
        + [_learned(f"pad {index}") for index in range(11)],
    )

    await compactor.compact(
        "LEARNED.md", trigger="manual", actor="user", session_id="sess-9"
    )
    await drain_memory_audits()

    trail = store.memory_dir / "audit" / "memory_audit.jsonl"
    record = json.loads(trail.read_text(encoding="utf-8").splitlines()[-1])

    assert record["action"] == "memory.compact"
    assert record["file"] == "LEARNED.md"
    assert record["actor"] == "user"
    assert record["session_id"] == "sess-9"
    assert "trigger=manual" in record["reason"]
    assert "archived=1" in record["reason"]
    assert record["ts"]


async def test_files_without_a_strategy_are_left_alone(store, compactor):
    store.append("PROJECT.md", "x" * (MDStore.DEFAULT_MAX_BYTES + 1))

    assert store.needs_compaction("PROJECT.md")
    assert await compactor.compact_if_needed("PROJECT.md") is False
    with pytest.raises(ValueError, match="no compaction strategy"):
        await compactor.compact("PROJECT.md")
    assert store.read("PROJECT.md").count("x") == MDStore.DEFAULT_MAX_BYTES + 1


async def test_compact_if_needed_is_false_under_budget(store, compactor):
    store.append("LEARNED.md", "small")

    assert await compactor.compact_if_needed("LEARNED.md") is False


def test_get_compactor_is_cached_per_path(tmp_path):
    first = get_compactor(tmp_path / "a")

    assert get_compactor(tmp_path / "a") is first
    assert get_compactor(tmp_path / "b") is not first
