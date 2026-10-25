"""MemoryItem model tests (M-25) — ARCHITECT6 §3.1.1 record format."""

from __future__ import annotations

from app.core.memory import MemoryItem, kind_for, next_id, parse_entries


def test_to_markdown_matches_spec_record_format():
    item = MemoryItem.create(
        "fact",
        "Project uses PostgreSQL 16.",
        id="fact_001",
        confidence=1.0,
        source="user_explicit",
        ts="2026-10-20T10:10:00Z",
    )

    assert item.to_markdown() == (
        "- [fact] id=fact_001 | confidence=1.0 | source=user_explicit"
        " | ts=2026-10-20T10:10:00Z\n"
        "  Project uses PostgreSQL 16.\n"
        "\n"
    )


def test_to_markdown_keeps_multi_line_text_indented():
    item = MemoryItem.create(
        "learned",
        "Scenario: refactor extract function.\nPattern: grep -> read -> edit.",
        id="learn_001",
        ts="2026-10-20T10:05:00Z",
    )

    rendered = item.to_markdown()

    assert "  Scenario: refactor extract function.\n" in rendered
    assert "  Pattern: grep -> read -> edit.\n" in rendered


def test_round_trip_through_parse_entries():
    original = MemoryItem.create(
        "preference",
        "User prefers tabs, not spaces.",
        id="pref_001",
        confidence=0.95,
        source="user_explicit",
        ts="2026-10-20T10:00:00Z",
    )

    parsed = parse_entries(original.to_markdown())

    assert parsed == [original]


def test_parse_entries_reads_a_whole_file():
    content = (
        MemoryItem.create(
            "fact", "Uses PostgreSQL 16.", id="fact_001", ts="2026-10-20T10:10:00Z"
        ).to_markdown()
        + MemoryItem.create(
            "fact", "Make needs Git Bash.", id="fact_002", ts="2026-10-20T10:11:00Z"
        ).to_markdown()
    )

    assert [item.id for item in parse_entries(content)] == ["fact_001", "fact_002"]


def test_parse_entries_treats_freeform_blocks_as_manual_entries():
    parsed = parse_entries(
        "hand-written note\n\nanother note\n", default_kind="learned"
    )

    assert len(parsed) == 2
    assert parsed[0].kind == "learned"
    assert parsed[0].text == "hand-written note"
    assert parsed[0].id is None
    assert parsed[0].source == "manual"
    assert parsed[0].confidence == 1.0


def test_parse_entries_skips_headers_without_default_kind():
    assert parse_entries("# Section\n\njust text\n") == []
    assert parse_entries("") == []
    assert parse_entries("   \n\n") == []


def test_parse_entries_tolerates_hand_edited_meta_lines():
    parsed = parse_entries(
        "- [decision] id=dec_007 | confidence=0.5 | source=manual"
        " | ts=2026-10-20T10:15:00Z\n  ADR-001: MCP as the tool contract.\n"
    )

    assert parsed[0].id == "dec_007"
    assert parsed[0].confidence == 0.5
    assert parsed[0].kind == "decision"


def test_next_id_is_monotonic_and_skips_gaps():
    content = "- [fact] id=fact_001 | ts=x\n  a\n\n- [fact] id=fact_003 | ts=x\n  b\n"

    assert next_id(content, "fact") == "fact_004"
    assert next_id("", "fact") == "fact_001"
    assert next_id("", "preference") == "pref_001"


def test_kind_for_filename():
    assert kind_for("LEARNED.md") == "learned"
    assert kind_for("PREFERENCES.md") == "preference"
    assert kind_for("PROJECT.md") == "project"
    assert kind_for("UNKNOWN.md") == "fact"
