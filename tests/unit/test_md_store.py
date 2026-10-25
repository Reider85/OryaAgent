"""MDStore L0 tests (M-25) — AC trace from BACKLOG6 M-25 + PROMPT_MVP §3.7."""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import threading
import time

import pytest

from app.core.memory import (
    FILES,
    MDStore,
    drain_memory_audits,
    get_md_store,
)


@pytest.fixture
def store(tmp_path) -> MDStore:
    return MDStore(tmp_path / "memory")


# --- constructor ------------------------------------------------------------


def test_constructor_creates_dir_and_six_empty_files(tmp_path):
    memory_dir = tmp_path / "memory"
    assert not memory_dir.exists()

    MDStore(memory_dir)

    assert memory_dir.is_dir()
    assert len(FILES) == 6
    for name in FILES:
        path = memory_dir / name
        assert path.is_file()
        assert path.read_text(encoding="utf-8") == ""


def test_constructor_never_truncates_existing_files(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "PROJECT.md").write_text("Mission: ship it.", encoding="utf-8")

    MDStore(memory_dir)

    assert (memory_dir / "PROJECT.md").read_text(encoding="utf-8") == (
        "Mission: ship it."
    )


def test_get_md_store_is_cached_per_path(tmp_path):
    first = get_md_store(tmp_path / "a")

    assert get_md_store(tmp_path / "a") is first
    assert get_md_store(tmp_path / "b") is not first
    assert first.memory_dir == tmp_path / "a"


# --- append: durability, atomicity, normalisation ---------------------------


def test_append_writes_to_end(store):
    store.append("LEARNED.md", "first")
    store.append("LEARNED.md", "second\n\n")

    assert store.read("LEARNED.md") == "first\n\nsecond\n\n"


def test_append_fsyncs_the_file(store, monkeypatch):
    calls: list[int] = []
    real_fsync = os.fsync

    def spy(fd: int) -> int:
        calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", spy)
    store.append("LEARNED.md", "durable")

    assert len(calls) == 1


def test_append_uses_a_single_write_syscall(store, monkeypatch):
    """Single O_APPEND write = the all-or-nothing guarantee (no torn records)."""
    payloads: list[bytes] = []
    real_write = os.write

    def spy(fd: int, data: bytes) -> int:
        payloads.append(bytes(data))
        return real_write(fd, data)

    monkeypatch.setattr(os, "write", spy)
    store.append("FACTS.md", "one-shot")

    assert payloads == [b"one-shot\n\n"]


def test_failed_append_keeps_previous_content(store, monkeypatch):
    store.append("LEARNED.md", "first")

    def boom(fd: int, data: bytes) -> int:
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "write", boom)
    with pytest.raises(OSError):
        store.append("LEARNED.md", "second")

    assert store.read("LEARNED.md") == "first\n\n"


def test_concurrent_appends_lose_no_updates(tmp_path):
    store = MDStore(tmp_path / "memory")
    errors: list[BaseException] = []

    def worker(index: int) -> None:
        try:
            for turn in range(10):
                store.append("LEARNED.md", f"entry-{index}-{turn}")
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors
    entries = [
        line
        for line in store.read("LEARNED.md").splitlines()
        if line.startswith("entry-")
    ]
    assert len(entries) == 100
    assert len(set(entries)) == 100, "every append survived — no lost updates"


def test_unknown_filename_is_rejected(store):
    with pytest.raises(ValueError, match="unknown memory file"):
        store.append("SECRETS.md", "x")
    with pytest.raises(ValueError, match="unknown memory file"):
        store.read("SECRETS.md")


# --- reads, mtime, stats ----------------------------------------------------


def test_read_all_returns_every_file(store):
    store.append("LEARNED.md", "note")

    everything = store.read_all()

    assert list(everything) == list(FILES)
    assert everything["LEARNED.md"] == "note\n\n"
    assert everything["PROJECT.md"] == ""


def test_mtime_reflects_writes(store):
    store.append("LEARNED.md", "entry")

    assert store.mtime("LEARNED.md") > 0
    assert store.mtime("MEMORY_INDEX.md") > 0
    (store.memory_dir / "PROJECT.md").unlink()
    assert store.mtime("PROJECT.md") == 0.0


def test_stats_reports_size_entries_and_last_write(store):
    store.append(
        "PREFERENCES.md",
        "- [preference] id=pref_001 | confidence=0.95 | source=user_explicit"
        " | ts=2026-10-20T10:00:00Z\n  tabs over spaces.",
    )

    stats = store.stats()

    assert set(stats) == set(FILES)
    preferences = stats["PREFERENCES.md"]
    assert preferences["bytes"] > 0
    assert preferences["entries"] == 1
    assert preferences["last_write"].endswith("Z")
    assert preferences["max_bytes"] == 2048
    assert preferences["over_limit"] is False
    assert stats["LEARNED.md"]["max_bytes"] == 4096
    index = stats["MEMORY_INDEX.md"]
    assert index["bytes"] == 0
    assert index["entries"] == 0
    assert index["max_bytes"] == 8192
    assert index["over_limit"] is False


def test_stats_counts_hand_edited_freeform_entries(store):
    (store.memory_dir / "FACTS.md").write_text(
        "just a line\n\nand another\n", encoding="utf-8"
    )

    assert store.stats()["FACTS.md"]["entries"] == 2


# --- performance (AC: 500 bytes < 1 ms) -------------------------------------


def test_append_500_bytes_completes_within_latency_budget(store, monkeypatch) -> None:
    """AC: a 500-byte append is a fast write (spec target < 1 ms).

    Measured on the Windows dev box: median ~3.5 ms for the full call —
    ``os.open``/``close`` alone cost ~2 ms there while ``fsync`` is 0.07 ms,
    so the POSIX sub-millisecond target cannot be asserted on win32. The
    documented deviation (M-25 plan) is a 5 ms budget; the compaction probe
    is stubbed out so the number reflects the write path + audit record.
    """
    monkeypatch.setattr(store, "needs_compaction", lambda file: False)
    payload = "x" * 500
    for _ in range(3):  # warm-up: first-touch and fsync costs
        store.append("LEARNED.md", payload)

    samples = []
    for _ in range(20):
        start = time.perf_counter()
        store.append("LEARNED.md", payload)
        samples.append(time.perf_counter() - start)

    median = statistics.median(samples)
    assert median < 0.005, (
        f"500-byte append median {median * 1000:.3f} ms exceeds the 5 ms budget"
    )


# --- compaction (M-25 hook -> M-27 Compactor) ---------------------------------


async def test_over_budget_append_schedules_compaction(tmp_path, monkeypatch):
    store = MDStore(tmp_path / "memory")
    calls: list[str] = []

    async def spy(file: str) -> bool:
        calls.append(file)
        return True

    monkeypatch.setattr(store, "compact_if_needed", spy)
    store.append("LEARNED.md", "y" * (MDStore.MAX_BYTES["LEARNED.md"] + 10))
    await asyncio.sleep(0)

    assert calls == ["LEARNED.md"]


async def test_under_budget_append_schedules_nothing(tmp_path, monkeypatch):
    store = MDStore(tmp_path / "memory")
    calls: list[str] = []

    async def spy(file: str) -> bool:
        calls.append(file)
        return True

    monkeypatch.setattr(store, "compact_if_needed", spy)
    store.append("LEARNED.md", "small")
    await asyncio.sleep(0)

    assert calls == []


def _learned_block(index: int, fill: str) -> str:
    """One ARCHITECT6 §3.1.1 record with a stable id."""
    return (
        f"- [learned] id=learn_{index:03d} | confidence=0.95 | source=/learn"
        f" | ts=2026-10-20T10:00:00Z\n  pattern {index}: {fill}"
    )


async def test_compact_if_needed_runs_the_real_compactor(store):
    """M-25's stub is gone: an over-budget file is compacted into the archive."""
    assert await store.compact_if_needed("LEARNED.md") is False

    for index in range(20):
        store.append("LEARNED.md", _learned_block(index, "x" * 250))
    assert store.needs_compaction("LEARNED.md")

    assert await store.compact_if_needed("LEARNED.md") is True

    assert not store.needs_compaction("LEARNED.md")
    content = store.read("LEARNED.md")
    assert content.count("- [learned]") < 20, "the oldest entries moved out"
    assert "pattern 19:" in content, "the newest entry survived"
    archive_dir = store.memory_dir / "archive"
    assert archive_dir.is_dir()
    archived = next(archive_dir.glob("LEARNED_*.md")).read_text(encoding="utf-8")
    assert "pattern 0:" in archived


async def test_scheduled_hook_eventually_compacts_the_file(store):
    """``_maybe_compact`` (M-25) now performs the real compaction asynchronously."""
    for index in range(20):
        store.append("LEARNED.md", _learned_block(index, "y" * 250))
    assert store.needs_compaction("LEARNED.md")

    deadline = time.monotonic() + 10
    while store.needs_compaction("LEARNED.md") and time.monotonic() < deadline:
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.05)  # let any trailing scheduled pass finish

    assert not store.needs_compaction("LEARNED.md"), "the scheduled task compacted it"
    assert store.read("LEARNED.md").count("- [learned]") < 20


def test_rewrite_is_atomic_and_locked(store):
    """The compaction primitive: tmp + os.replace under the per-file lock."""
    store.append("LEARNED.md", "old")

    def transform(old: str) -> str:
        return old.replace("old", "new")

    body = store.rewrite("LEARNED.md", transform)

    assert body == "new\n\n"
    assert store.read("LEARNED.md") == body
    assert list(store.memory_dir.glob(".*.tmp")) == []
    # a transform that returns the input unchanged must not write at all
    before = store.mtime("LEARNED.md")
    assert store.rewrite("LEARNED.md", lambda old: old) == body
    assert store.mtime("LEARNED.md") == before


# --- audit trail (best-effort, M-25 decision) --------------------------------


def test_append_records_audit_jsonl(store):
    store.append(
        "LEARNED.md",
        "- [learned] id=learn_001 | confidence=1.0 | source=/learn"
        " | ts=2026-10-20T10:05:00Z\n  pattern",
    )

    trail = store.memory_dir / "audit" / "memory_audit.jsonl"
    record = json.loads(trail.read_text(encoding="utf-8").splitlines()[-1])

    assert record["action"] == "memory.append"
    assert record["file"] == "LEARNED.md"
    assert record["actor"] == "user"
    assert record["reason"] is None
    assert record["preview"].startswith("- [learned] id=learn_001")
    assert record["ts"]


async def test_append_inserts_audit_row_when_pool_is_up(store, monkeypatch):
    executed: list[tuple[str, tuple]] = []

    class _Pool:
        async def execute(self, sql: str, *args) -> str:
            executed.append((sql, args))
            return "INSERT 0 1"

    monkeypatch.setattr("app.db.get_pool_if_created", lambda: _Pool())
    store.append("FACTS.md", "PostgreSQL 16", session_id="s-1")
    await drain_memory_audits()

    assert len(executed) == 1
    sql, args = executed[0]
    assert "INSERT INTO memory_audit_log" in sql
    assert args[1] == "memory.append"
    assert args[2] == "FACTS.md"
    assert args[5] == "s-1"
    assert not (store.memory_dir / "audit" / "memory_audit.jsonl").exists()


async def test_append_audit_falls_back_to_jsonl_without_pool(store, monkeypatch):
    monkeypatch.setattr("app.db.get_pool_if_created", lambda: None)

    store.append("PROJECT.md", "Mission: ship it.")
    await drain_memory_audits()

    trail = store.memory_dir / "audit" / "memory_audit.jsonl"
    record = json.loads(trail.read_text(encoding="utf-8").splitlines()[-1])
    assert record["file"] == "PROJECT.md"
    assert record["preview"] == "Mission: ship it.\n\n"


async def test_audit_failure_never_breaks_an_append(store, monkeypatch):
    class _Pool:
        async def execute(self, sql: str, *args) -> str:
            raise RuntimeError("connection lost")

    monkeypatch.setattr("app.db.get_pool_if_created", lambda: _Pool())
    store.append("DECISIONS.md", "- [decision] MCP as the tool contract.")
    await drain_memory_audits()

    assert store.read("DECISIONS.md").startswith("- [decision]")
    trail = store.memory_dir / "audit" / "memory_audit.jsonl"
    assert (
        json.loads(trail.read_text(encoding="utf-8").splitlines()[-1])["file"]
        == "DECISIONS.md"
    )
