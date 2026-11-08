"""Tests for BranchManager merge functionality (B-10)."""

import asyncio
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.branch_manager import BranchManager
from app.core.session import SessionManager


class TestBranchManagerMerge:
    """Test cases for branch merge functionality."""

    @pytest.fixture
    def branch_manager(self):
        """Create a BranchManager instance for testing."""
        with patch(
            "app.core.branch_manager.get_session_manager"
        ) as mock_session_manager:
            with patch("app.core.branch_manager.get_md_store") as mock_md_store:
                mock_session_manager.return_value = AsyncMock()
                mock_md_store.return_value = AsyncMock()

                manager = BranchManager()
                manager.session_manager = mock_session_manager.return_value
                manager.md_store = mock_md_store.return_value
                return manager

    @pytest.fixture
    def mock_sessions(self):
        """Create mock session data for testing."""
        return {
            "source_session": {
                "id": "source-123",
                "name": "test-branch",
                "parent_session_id": "parent-123",
                "parent_turn_id": "turn-456",
                "created_at": datetime.utcnow(),
                "status": "active",
                "metadata": {"branch_name": "test-branch"},
            },
            "target_session": {
                "id": "target-123",
                "name": "main-session",
                "created_at": datetime.utcnow(),
                "status": "active",
                "metadata": {},
            },
        }

    @pytest.fixture
    def mock_turns(self):
        """Create mock turn data for testing."""
        return {
            "source_turns": [
                {
                    "id": "turn-1",
                    "session_id": "source-123",
                    "turn_number": 1,
                    "messages": [{"role": "user", "content": "Hello"}],
                    "tool_calls": [],
                    "created_at": datetime.utcnow(),
                    "metadata": {},
                },
                {
                    "id": "turn-2",
                    "session_id": "source-123",
                    "turn_number": 2,
                    "messages": [{"role": "assistant", "content": "Hi there!"}],
                    "tool_calls": [],
                    "created_at": datetime.utcnow(),
                    "metadata": {},
                },
            ],
            "target_turns": [
                {
                    "id": "turn-3",
                    "session_id": "target-123",
                    "turn_number": 1,
                    "messages": [{"role": "user", "content": "Start here"}],
                    "tool_calls": [],
                    "created_at": datetime.utcnow(),
                    "metadata": {},
                }
            ],
        }

    @pytest.mark.asyncio
    async def test_merge_branches_append_strategy(
        self, branch_manager, mock_sessions, mock_turns
    ):
        """Test merge with append strategy."""
        # Setup mocks
        branch_manager.session_manager.get_session.side_effect = lambda session_id: (
            mock_sessions.get(session_id)
        )
        branch_manager.session_manager.get_session_turns.side_effect = (
            lambda session_id: mock_turns.get(f"{session_id}_turns", [])
        )
        branch_manager.session_manager.create_turn = AsyncMock()

        # Perform merge
        result = await branch_manager.merge_branches(
            source_session_id="source-123",
            target_session_id="target-123",
            merge_strategy="append",
            conflict_resolution="manual",
        )

        # Verify results
        assert result["success"] is True
        assert result["source_session"] == "test-branch"
        assert result["target_session"] == "main-session"
        assert result["merge_strategy"] == "append"
        assert result["merged_turns"] == 2

        # Verify that turns were created
        assert branch_manager.session_manager.create_turn.call_count == 2

    @pytest.mark.asyncio
    async def test_merge_branches_interleave_strategy(
        self, branch_manager, mock_sessions, mock_turns
    ):
        """Test merge with interleave strategy."""
        # Setup mocks
        branch_manager.session_manager.get_session.side_effect = lambda session_id: (
            mock_sessions.get(session_id)
        )
        branch_manager.session_manager.get_session_turns.side_effect = (
            lambda session_id: mock_turns.get(f"{session_id}_turns", [])
        )
        branch_manager.session_manager.create_turn = AsyncMock()

        # Perform merge
        result = await branch_manager.merge_branches(
            source_session_id="source-123",
            target_session_id="target-123",
            merge_strategy="interleave",
            conflict_resolution="manual",
        )

        # Verify results
        assert result["success"] is True
        assert result["merge_strategy"] == "interleave"
        assert result["merged_turns"] == 2

    @pytest.mark.asyncio
    async def test_merge_branches_replace_strategy(
        self, branch_manager, mock_sessions, mock_turns
    ):
        """Test merge with replace strategy."""
        # Setup mocks
        branch_manager.session_manager.get_session.side_effect = lambda session_id: (
            mock_sessions.get(session_id)
        )
        branch_manager.session_manager.get_session_turns.side_effect = (
            lambda session_id: mock_turns.get(f"{session_id}_turns", [])
        )
        branch_manager.session_manager.create_turn = AsyncMock()

        # Perform merge
        result = await branch_manager.merge_branches(
            source_session_id="source-123",
            target_session_id="target-123",
            merge_strategy="replace",
            conflict_resolution="manual",
        )

        # Verify results
        assert result["success"] is True
        assert result["merge_strategy"] == "replace"
        assert result["merged_turns"] == 2

    @pytest.mark.asyncio
    async def test_merge_branches_invalid_strategy(self, branch_manager, mock_sessions):
        """Test merge with invalid strategy."""
        branch_manager.session_manager.get_session.side_effect = lambda session_id: (
            mock_sessions.get(session_id)
        )

        with pytest.raises(ValueError, match="Unknown merge strategy"):
            await branch_manager.merge_branches(
                source_session_id="source-123",
                target_session_id="target-123",
                merge_strategy="invalid_strategy",
                conflict_resolution="manual",
            )

    @pytest.mark.asyncio
    async def test_merge_branches_missing_source_session(
        self, branch_manager, mock_sessions
    ):
        """Test merge with missing source session."""
        branch_manager.session_manager.get_session.side_effect = lambda session_id: (
            mock_sessions.get(session_id)
        )

        with pytest.raises(ValueError, match="Source session not found"):
            await branch_manager.merge_branches(
                source_session_id="missing-session",
                target_session_id="target-123",
                merge_strategy="append",
                conflict_resolution="manual",
            )

    @pytest.mark.asyncio
    async def test_merge_branches_missing_target_session(
        self, branch_manager, mock_sessions
    ):
        """Test merge with missing target session."""
        branch_manager.session_manager.get_session.side_effect = lambda session_id: (
            mock_sessions.get(session_id)
        )

        with pytest.raises(ValueError, match="Target session not found"):
            await branch_manager.merge_branches(
                source_session_id="source-123",
                target_session_id="missing-session",
                merge_strategy="append",
                conflict_resolution="manual",
            )

    @pytest.mark.asyncio
    async def test_merge_memory_files(self, branch_manager):
        """Test memory file merging functionality."""
        # Setup mock memory directories
        source_memory_dir = Path("/tmp/source_memory")
        target_memory_dir = Path("/tmp/target_memory")

        source_memory_dir.mkdir(parents=True, exist_ok=True)
        target_memory_dir.mkdir(parents=True, exist_ok=True)

        # Create test memory files
        test_files = ["PROJECT.md", "LEARNED.md", "PREFERENCES.md"]
        for file_name in test_files:
            (source_memory_dir / file_name).write_text("Source content")
            (target_memory_dir / file_name).write_text("Target content")

        # Mock memory directory methods
        branch_manager.md_store.get_session_memory_dir.side_effect = lambda session_id: (
            {"source-123": source_memory_dir, "target-123": target_memory_dir}[
                session_id
            ]
        )

        # Perform memory merge
        await branch_manager._merge_memory_files("source-123", "target-123")

        # Verify merged content
        for file_name in test_files:
            merged_content = (target_memory_dir / file_name).read_text()
            assert "Source content" in merged_content
            assert "Target content" in merged_content
            assert "---" in merged_content  # Separator should be present

        # Cleanup
        import shutil

        shutil.rmtree(source_memory_dir)
        shutil.rmtree(target_memory_dir)

    @pytest.mark.asyncio
    async def test_merge_history_tracking(self, branch_manager, mock_sessions):
        """Test merge history tracking functionality."""
        branch_manager.session_manager.get_session.return_value = mock_sessions[
            "target_session"
        ]
        branch_manager.session_manager.update_session_metadata = AsyncMock()

        # Simulate merge history
        merge_history = [
            {
                "source_session_id": "source-123",
                "merge_strategy": "append",
                "merged_at": datetime.utcnow().isoformat(),
                "merged_turns": 2,
                "results": [{"turn_id": "turn-1", "turn_number": 1}],
            }
        ]

        mock_sessions["target_session"]["metadata"]["merge_history"] = merge_history

        # Get merge history
        history = await branch_manager.get_merge_history("target-123")

        # Verify history
        assert len(history) == 1
        assert history[0]["source_session_id"] == "source-123"
        assert history[0]["merge_strategy"] == "append"
        assert history[0]["merged_turns"] == 2

    @pytest.mark.asyncio
    async def test_merge_performance_metrics(self, branch_manager):
        """Test merge performance metrics."""
        with patch("asyncpg.get_pool") as mock_pool:
            mock_conn = AsyncMock()
            mock_pool.return_value.acquire.return_value.__aenter__.return_value = (
                mock_conn
            )

            # Mock database responses
            mock_conn.fetchval.return_value = 5  # branch count
            mock_conn.fetchrow.return_value = {
                "branch_id": "branch-123",
                "branch_name": "test-branch",
                "turn_count": 10,
            }

            # Get performance metrics
            metrics = await branch_manager.get_branch_performance_metrics("session-123")

            # Verify metrics
            assert metrics["branch_count"] == 5
            assert metrics["largest_branch"]["turn_count"] == 10
            assert "branch_id" in metrics["largest_branch"]

    @pytest.mark.asyncio
    async def test_merge_with_tool_calls(self, branch_manager, mock_sessions):
        """Test merge with tool calls in turns."""
        # Setup turns with tool calls
        turns_with_tools = {
            "source_turns": [
                {
                    "id": "turn-1",
                    "session_id": "source-123",
                    "turn_number": 1,
                    "messages": [{"role": "user", "content": "Create a file"}],
                    "tool_calls": [
                        {
                            "id": "tool-1",
                            "name": "write",
                            "args": {"path": "test.txt", "content": "Hello"},
                            "result": "File created",
                        }
                    ],
                    "created_at": datetime.utcnow(),
                    "metadata": {},
                }
            ],
            "target_turns": [],
        }

        branch_manager.session_manager.get_session.side_effect = lambda session_id: (
            mock_sessions.get(session_id)
        )
        branch_manager.session_manager.get_session_turns.side_effect = (
            lambda session_id: turns_with_tools.get(f"{session_id}_turns", [])
        )
        branch_manager.session_manager.create_turn = AsyncMock()

        # Perform merge
        result = await branch_manager.merge_branches(
            source_session_id="source-123",
            target_session_id="target-123",
            merge_strategy="append",
            conflict_resolution="manual",
        )

        # Verify tool calls are preserved
        created_turn_calls = branch_manager.session_manager.create_turn.call_args[0][0][
            "tool_calls"
        ]
        assert len(created_turn_calls) == 1
        assert created_turn_calls[0]["name"] == "write"
        assert created_turn_calls[0]["args"]["path"] == "test.txt"

    @pytest.mark.asyncio
    async def test_merge_conflict_resolution_auto(
        self, branch_manager, mock_sessions, mock_turns
    ):
        """Test merge with automatic conflict resolution."""
        branch_manager.session_manager.get_session.side_effect = lambda session_id: (
            mock_sessions.get(session_id)
        )
        branch_manager.session_manager.get_session_turns.side_effect = (
            lambda session_id: mock_turns.get(f"{session_id}_turns", [])
        )
        branch_manager.session_manager.create_turn = AsyncMock()

        # Perform merge with auto conflict resolution
        result = await branch_manager.merge_branches(
            source_session_id="source-123",
            target_session_id="target-123",
            merge_strategy="append",
            conflict_resolution="auto",
        )

        # Verify results
        assert result["success"] is True
        assert result["conflict_resolution"] == "auto"
        assert result["merged_turns"] == 2

    @pytest.mark.asyncio
    async def test_merge_conflict_resolution_source(
        self, branch_manager, mock_sessions, mock_turns
    ):
        """Test merge with source conflict resolution."""
        branch_manager.session_manager.get_session.side_effect = lambda session_id: (
            mock_sessions.get(session_id)
        )
        branch_manager.session_manager.get_session_turns.side_effect = (
            lambda session_id: mock_turns.get(f"{session_id}_turns", [])
        )
        branch_manager.session_manager.create_turn = AsyncMock()

        # Perform merge with source conflict resolution
        result = await branch_manager.merge_branches(
            source_session_id="source-123",
            target_session_id="target-123",
            merge_strategy="append",
            conflict_resolution="source",
        )

        # Verify results
        assert result["success"] is True
        assert result["conflict_resolution"] == "source"
        assert result["merged_turns"] == 2
