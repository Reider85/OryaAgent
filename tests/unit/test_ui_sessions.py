"""Unit tests for M-17 — app.ui.sessions (session listing, title enrichment).

Tests session listing from JSONL files, title extraction, and database
enrichment. No database needed for most tests — file operations only.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.ui.sessions import (
    SessionInfo,
    enrich_titles_from_db,
    get_session_count,
    list_sessions,
)


class TestSessionInfo:
    """Test SessionInfo dataclass."""

    def test_display_name_with_title(self) -> None:
        """Test display name when title is available."""
        info = SessionInfo(
            session_id="abc123",
            title="My Project",
            last_modified=1234567890.0,
            message_count=5,
        )
        assert info.display_name == "My Project"

    def test_display_name_without_title(self) -> None:
        """Test display name fallback to session_id prefix."""
        info = SessionInfo(
            session_id="abc123def456",
            title=None,
            last_modified=1234567890.0,
            message_count=3,
        )
        assert info.display_name == "Session abc123de"

    def test_display_name_long_title(self) -> None:
        """Test display name with a long title (no truncation at this layer)."""
        long_content = "This is a very long title that should be truncated"
        info = SessionInfo(
            session_id="abc123",
            title=long_content,
            last_modified=1234567890.0,
            message_count=1,
        )
        assert info.display_name == long_content


class TestListSessions:
    """Test session listing from JSONL files."""

    async def test_list_sessions_empty_directory(self) -> None:
        """Test listing sessions in empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions = await list_sessions(Path(tmpdir))
            assert sessions == []

    async def test_list_sessions_no_jsonl_files(self) -> None:
        """Test listing when no JSONL files exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "other.txt").touch()  # Non-JSONL file
            sessions = await list_sessions(Path(tmpdir))
            assert sessions == []

    async def test_list_sessions_jsonl_files(self) -> None:
        """Test listing JSONL files with proper metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)

            # Create test JSONL files
            session1 = sessions_dir / "abc123.jsonl"
            session1.write_text(
                '{"ts": "2024-01-01T10:00:00", "type": "user", "payload": {"message_id": "Hello"}}\n'
                '{"ts": "2024-01-01T10:01:00", "type": "assistant", "payload": {"message_id": "Hi there"}}\n'
            )

            session2 = sessions_dir / "def456.jsonl"
            session2.write_text(
                '{"ts": "2024-01-01T09:00:00", "type": "user", "payload": {"message_id": "Start"}}\n'
            )

            # Add a non-JSONL file
            (sessions_dir / "readme.txt").touch()

            sessions = await list_sessions(sessions_dir, limit=10)

            assert len(sessions) == 2
            assert all(isinstance(s, SessionInfo) for s in sessions)

            # Check metadata
            by_id = {s.session_id: s for s in sessions}
            assert by_id["abc123"].title == "Hello"
            assert by_id["abc123"].message_count == 2
            assert by_id["def456"].title == "Start"
            assert by_id["def456"].message_count == 1

    async def test_list_sessions_limit(self) -> None:
        """Test limiting number of returned sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)

            # Create 5 JSONL files
            for i in range(5):
                session_file = sessions_dir / f"session{i}.jsonl"
                session_file.write_text(
                    '{"ts": "2024-01-01T10:00:00", "type": "user", "payload": {"message_id": "Message"}}\n'
                )

            # Get only 3 sessions
            sessions = await list_sessions(sessions_dir, limit=3)
            assert len(sessions) == 3

    async def test_list_sessions_corrupt_file(self) -> None:
        """Test handling of corrupt JSONL files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)

            # Valid file
            valid_file = sessions_dir / "valid.jsonl"
            valid_file.write_text(
                '{"ts": "2024-01-01T10:00:00", "type": "user", "payload": {"message_id": "Valid"}}\n'
            )

            # Corrupt file
            corrupt_file = sessions_dir / "corrupt.jsonl"
            corrupt_file.write_text("not json {")

            # Empty file
            empty_file = sessions_dir / "empty.jsonl"
            empty_file.touch()

            sessions = await list_sessions(sessions_dir)

            # Corrupt/empty files produce sessions with no title but are still listed
            assert len(sessions) >= 1
            by_id = {s.session_id: s for s in sessions}
            assert by_id["valid"].title == "Valid"

    async def test_list_sessions_no_user_messages(self) -> None:
        """Test files with no user messages (no title)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)

            # File with only assistant messages
            session_file = sessions_dir / "no_user.jsonl"
            session_file.write_text(
                '{"ts": "2024-01-01T10:00:00", "type": "assistant", "payload": {"message_id": "Hello"}}\n'
            )

            sessions = await list_sessions(sessions_dir)

            assert len(sessions) == 1
            assert sessions[0].session_id == "no_user"
            assert sessions[0].title is None

    async def test_list_sessions_with_pool(self) -> None:
        """Test listing with database pool (should not fail if pool is None)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)
            session_file = sessions_dir / "test.jsonl"
            session_file.write_text(
                '{"ts": "2024-01-01T10:00:00", "type": "user", "payload": {"message_id": "Test"}}\n'
            )

            # Test with None pool
            sessions = await list_sessions(sessions_dir, pool=None)
            assert len(sessions) == 1
            assert sessions[0].session_id == "test"


class TestEnrichTitlesFromDb:
    """Test database enrichment of session titles."""

    @pytest.mark.asyncio
    async def test_enrich_titles_empty_list(self) -> None:
        """Test enrichment with empty session list."""
        sessions = []
        enriched = await enrich_titles_from_db(sessions)
        assert enriched == []

    @pytest.mark.asyncio
    async def test_enrich_titles_no_db(self) -> None:
        """Test enrichment without database pool."""
        sessions = [
            SessionInfo(session_id="abc123", title="Existing"),
            SessionInfo(session_id="def456", title=None),
        ]

        enriched = await enrich_titles_from_db(sessions)

        # Should return unchanged sessions
        assert len(enriched) == 2
        assert enriched[0].title == "Existing"  # Unchanged
        assert enriched[1].title is None  # Still None

    @pytest.mark.asyncio
    @patch("app.ui.sessions.get_asyncpg_pool")
    async def test_enrich_titles_with_db(self, mock_get_pool) -> None:
        """Test enrichment with database pool."""
        # Mock database pool
        mock_pool = AsyncMock()
        mock_get_pool.return_value = mock_pool

        # Mock database response
        mock_pool.fetch.return_value = [
            {"session_id": "def456", "title": "From Database"},
            {"session_id": "ghi789", "title": "Another Title"},
        ]

        sessions = [
            SessionInfo(session_id="abc123", title="Existing"),
            SessionInfo(session_id="def456", title=None),
            SessionInfo(session_id="ghi789", title=None),
        ]

        enriched = await enrich_titles_from_db(sessions, pool=mock_pool)

        # Should enrich only sessions without titles
        assert len(enriched) == 3
        assert enriched[0].title == "Existing"  # Unchanged (had title)
        assert enriched[1].title == "From Database"  # Enriched
        assert enriched[2].title == "Another Title"  # Enriched

        # Verify database query
        mock_pool.fetch.assert_called_once()
        call_args = mock_pool.fetch.call_args
        query = call_args[0][0]
        assert "session_id" in query
        assert "ANY($1)" in query
        assert call_args[0][1] == ["abc123", "def456", "ghi789"]

    @pytest.mark.asyncio
    @patch("app.ui.sessions.get_asyncpg_pool")
    async def test_enrich_titles_db_error(self, mock_get_pool) -> None:
        """Test enrichment when database fails."""
        # Mock database error
        mock_get_pool.side_effect = Exception("Database connection failed")

        sessions = [
            SessionInfo(session_id="abc123", title="Existing"),
            SessionInfo(session_id="def456", title=None),
        ]

        enriched = await enrich_titles_from_db(sessions)

        # Should return original sessions unchanged
        assert len(enriched) == 2
        assert enriched[0].title == "Existing"
        assert enriched[1].title is None

    @pytest.mark.asyncio
    async def test_enrich_titles_with_pool_arg(self) -> None:
        """Test enrichment with explicit pool argument."""
        sessions = [SessionInfo(session_id="abc123", title=None)]

        # Test with None pool
        enriched = await enrich_titles_from_db(sessions, pool=None)
        assert len(enriched) == 1
        assert enriched[0].title is None


class TestGetSessionCount:
    """Test session counting (stubbed for now)."""

    @pytest.mark.asyncio
    async def test_get_session_count_empty(self) -> None:
        """Test counting with no sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            count = await get_session_count(Path(tmpdir))
            assert count == 0

    @pytest.mark.asyncio
    async def test_get_session_count_with_files(self) -> None:
        """Test counting with JSONL files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir)

            # Create some JSONL files
            for i in range(3):
                (sessions_dir / f"session{i}.jsonl").touch()

            count = await get_session_count(sessions_dir)
            assert count == 3
