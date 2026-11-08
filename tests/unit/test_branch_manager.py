"""Unit tests for BranchManager functionality (B-09).

Tests the core branch creation, management, and merging functionality.
"""

import asyncio
import pytest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.core.branch_manager import BranchManager, get_branch_manager
from app.core.memory.md_store import MDStore
from app.core.session import SessionManager


class TestBranchManager:
    """Test suite for BranchManager functionality."""

    @pytest.fixture
    def branch_manager(self):
        """Create a BranchManager instance for testing."""
        return BranchManager()

    @pytest.fixture
    def mock_session_manager(self):
        """Mock session manager for testing."""
        mock_manager = AsyncMock(spec=SessionManager)
        mock_manager.get_session = AsyncMock()
        mock_manager.get_session_turns = AsyncMock()
        mock_manager.get_turn = AsyncMock()
        mock_manager.create_session = AsyncMock()
        mock_manager.create_turn = AsyncMock()
        mock_manager.delete_session = AsyncMock()
        mock_manager.update_session_metadata = AsyncMock()
        return mock_manager

    @pytest.fixture
    def mock_md_store(self):
        """Mock MDStore for testing."""
        mock_store = AsyncMock(spec=MDStore)
        mock_store.get_session_memory_dir = MagicMock()
        return mock_store

    @pytest.fixture
    def sample_session(self):
        """Sample session data for testing."""
        return {
            "id": str(uuid.uuid4()),
            "name": "test-session",
            "created_at": datetime.utcnow(),
            "status": "active",
            "metadata": {},
        }

    @pytest.fixture
    def sample_turns(self):
        """Sample turns data for testing."""
        base_time = datetime.utcnow()
        return [
            {
                "id": str(uuid.uuid4()),
                "session_id": str(uuid.uuid4()),
                "turn_number": 1,
                "messages": [{"role": "user", "content": "Hello"}],
                "tool_calls": [],
                "created_at": base_time,
            },
            {
                "id": str(uuid.uuid4()),
                "session_id": str(uuid.uuid4()),
                "turn_number": 2,
                "messages": [{"role": "assistant", "content": "Hi there!"}],
                "tool_calls": [],
                "created_at": base_time + timedelta(seconds=1),
            },
        ]

    @pytest.fixture
    def sample_memory_dir(self, tmp_path):
        """Sample memory directory for testing."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()

        # Create sample memory files
        memory_files = [
            "PROJECT.md",
            "LEARNED.md",
            "PREFERENCES.md",
            "FACTS.md",
            "DECISIONS.md",
        ]
        for file_name in memory_files:
            (memory_dir / file_name).write_text(f"# Content of {file_name}")

        return memory_dir

    def test_get_branch_manager_singleton(self):
        """Test that get_branch_manager returns the same instance."""
        manager1 = get_branch_manager()
        manager2 = get_branch_manager()
        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_fork_session_success(
        self,
        branch_manager,
        mock_session_manager,
        mock_md_store,
        sample_session,
        sample_turns,
        sample_memory_dir,
    ):
        """Test successful session fork."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager
        branch_manager.md_store = mock_md_store

        mock_session_manager.get_session.return_value = sample_session
        mock_session_manager.get_session_turns.return_value = sample_turns
        mock_session_manager.get_turn.return_value = sample_turns[0]
        mock_session_manager.create_session.return_value = None
        mock_session_manager.create_turn.return_value = None

        mock_md_store.get_session_memory_dir.return_value = sample_memory_dir

        # Test fork
        branch_id = await branch_manager.fork_session(
            session_id=sample_session["id"],
            turn_id=sample_turns[0]["id"],
            branch_name="test-branch",
        )

        # Verify results
        assert isinstance(branch_id, str)
        assert len(branch_id) > 0

        # Verify session manager calls
        mock_session_manager.get_session.assert_called_once_with(sample_session["id"])
        mock_session_manager.get_session_turns.assert_called_once_with(
            sample_session["id"]
        )
        mock_session_manager.get_turn.assert_called_once_with(
            sample_session["id"], sample_turns[0]["id"]
        )
        mock_session_manager.create_session.assert_called_once()
        mock_session_manager.create_turn.assert_called_once()

    @pytest.mark.asyncio
    async def test_fork_session_no_turn_id_defaults_to_latest(
        self,
        branch_manager,
        mock_session_manager,
        mock_md_store,
        sample_session,
        sample_turns,
        sample_memory_dir,
    ):
        """Test that fork without turn_id defaults to latest turn."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager
        branch_manager.md_store = mock_md_store

        mock_session_manager.get_session.return_value = sample_session
        mock_session_manager.get_session_turns.return_value = sample_turns
        mock_session_manager.get_turn.return_value = sample_turns[-1]  # Latest turn
        mock_session_manager.create_session.return_value = None
        mock_session_manager.create_turn.return_value = None

        mock_md_store.get_session_memory_dir.return_value = sample_memory_dir

        # Test fork without turn_id
        branch_id = await branch_manager.fork_session(session_id=sample_session["id"])

        # Verify latest turn was used
        mock_session_manager.get_turn.assert_called_once_with(
            sample_session["id"], sample_turns[-1]["id"]
        )

    @pytest.mark.asyncio
    async def test_fork_session_no_turns_error(
        self, branch_manager, mock_session_manager, mock_md_store, sample_session
    ):
        """Test error when session has no turns."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager
        branch_manager.md_store = mock_md_store

        mock_session_manager.get_session.return_value = sample_session
        mock_session_manager.get_session_turns.return_value = []  # No turns

        # Test fork should raise error
        with pytest.raises(ValueError, match="No turns found"):
            await branch_manager.fork_session(session_id=sample_session["id"])

    @pytest.mark.asyncio
    async def test_fork_session_not_found_error(
        self, branch_manager, mock_session_manager
    ):
        """Test error when parent session not found."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager

        mock_session_manager.get_session.return_value = None

        # Test fork should raise error
        with pytest.raises(ValueError, match="Parent session not found"):
            await branch_manager.fork_session(session_id="non-existent-id")

    @pytest.mark.asyncio
    async def test_fork_session_turn_not_found_error(
        self,
        branch_manager,
        mock_session_manager,
        mock_md_store,
        sample_session,
        sample_turns,
    ):
        """Test error when specific turn not found."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager
        branch_manager.md_store = mock_md_store

        mock_session_manager.get_session.return_value = sample_session
        mock_session_manager.get_session_turns.return_value = sample_turns
        mock_session_manager.get_turn.return_value = None  # Turn not found

        # Test fork should raise error
        with pytest.raises(ValueError, match="Turn not found"):
            await branch_manager.fork_session(
                session_id=sample_session["id"], turn_id="non-existent-turn-id"
            )

    @pytest.mark.asyncio
    async def test_copy_session_state(
        self, branch_manager, mock_session_manager, sample_turns
    ):
        """Test session state copying functionality."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager

        parent_session_id = str(uuid.uuid4())
        branch_session_id = str(uuid.uuid4())
        parent_turn_id = sample_turns[0]["id"]

        # Test copy session state
        await branch_manager._copy_session_state(
            parent_session_id, branch_session_id, parent_turn_id
        )

        # Verify session manager calls
        assert mock_session_manager.create_turn.call_count == 1
        call_args = mock_session_manager.create_turn.call_args
        assert call_args[1]["session_id"] == branch_session_id
        assert call_args[1]["turn_number"] == sample_turns[0]["turn_number"]

    @pytest.mark.asyncio
    async def test_copy_memory_files(
        self, branch_manager, mock_md_store, sample_memory_dir
    ):
        """Test memory file copying functionality."""
        # Setup mocks
        branch_manager.md_store = mock_md_store

        parent_session_id = str(uuid.uuid4())
        branch_session_id = str(uuid.uuid4())

        # Mock memory directories
        mock_md_store.get_session_memory_dir.return_value = sample_memory_dir

        # Mock branch memory directory
        with patch.object(mock_md_store, "get_session_memory_dir") as mock_get_dir:
            branch_memory_dir = Path(tmp_path) / "branch_memory"
            branch_memory_dir.mkdir()
            mock_get_dir.side_effect = lambda sid: (
                sample_memory_dir if sid == parent_session_id else branch_memory_dir
            )

            # Test copy memory files
            await branch_manager._copy_memory_files(
                parent_session_id, branch_session_id
            )

            # Verify files were copied
            for file_name in [
                "PROJECT.md",
                "LEARNED.md",
                "PREFERENCES.md",
                "FACTS.md",
                "DECISIONS.md",
            ]:
                source_file = sample_memory_dir / file_name
                target_file = branch_memory_dir / file_name
                assert target_file.exists()
                assert target_file.read_text() == source_file.read_text()

    @pytest.mark.asyncio
    async def test_list_branches(self, branch_manager, mock_session_manager):
        """Test listing branches for a session."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager

        session_id = str(uuid.uuid4())
        expected_branches = [
            {
                "id": str(uuid.uuid4()),
                "name": "branch-1",
                "created_at": datetime.utcnow(),
                "status": "active",
                "metadata": {},
            },
            {
                "id": str(uuid.uuid4()),
                "name": "branch-2",
                "created_at": datetime.utcnow(),
                "status": "active",
                "metadata": {},
            },
        ]

        mock_session_manager.get_session_turns.return_value = []  # Mock DB call
        with patch("asyncpg.get_pool") as mock_pool:
            mock_conn = AsyncMock()
            mock_pool.return_value.acquire.return_value.__aenter__.return_value = (
                mock_conn
            )
            mock_conn.fetch.return_value = expected_branches

            # Test list branches
            branches = await branch_manager.list_branches(session_id)

            # Verify results
            assert len(branches) == 2
            assert branches[0]["name"] == "branch-1"
            assert branches[1]["name"] == "branch-2"

    @pytest.mark.asyncio
    async def test_get_branch_info(
        self, branch_manager, mock_session_manager, sample_session
    ):
        """Test getting branch information."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager

        branch_id = str(uuid.uuid4())
        mock_session_manager.get_session.return_value = sample_session

        # Test get branch info
        branch_info = await branch_manager.get_branch_info(branch_id)

        # Verify results
        assert branch_info is not None
        assert branch_info["id"] == branch_id
        assert branch_info["name"] == sample_session["name"]

    @pytest.mark.asyncio
    async def test_get_branch_info_not_found(
        self, branch_manager, mock_session_manager
    ):
        """Test getting non-existent branch information."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager

        branch_id = str(uuid.uuid4())
        mock_session_manager.get_session.return_value = None

        # Test get branch info
        branch_info = await branch_manager.get_branch_info(branch_id)

        # Verify results
        assert branch_info is None

    @pytest.mark.asyncio
    async def test_delete_branch(
        self, branch_manager, mock_session_manager, mock_md_store, sample_session
    ):
        """Test deleting a branch."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager
        branch_manager.md_store = mock_md_store

        branch_id = str(uuid.uuid4())
        mock_session_manager.get_session.return_value = sample_session

        # Mock memory directory
        with patch("shutil.rmtree") as mock_rmtree:
            mock_md_store.get_session_memory_dir.return_value = Path("/tmp/mock_memory")

            # Test delete branch
            success = await branch_manager.delete_branch(branch_id)

            # Verify results
            assert success is True
            mock_session_manager.delete_session.assert_called_once_with(branch_id)
            mock_rmtree.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_branch_not_found(self, branch_manager, mock_session_manager):
        """Test deleting non-existent branch."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager

        branch_id = str(uuid.uuid4())
        mock_session_manager.get_session.return_value = None

        # Test delete branch
        success = await branch_manager.delete_branch(branch_id)

        # Verify results
        assert success is False

    @pytest.mark.asyncio
    async def test_find_common_ancestor(self, branch_manager, sample_turns):
        """Test finding common ancestor between source and target turns."""
        # Test with target turns
        target_turns = sample_turns[:1]  # First turn
        source_turns = sample_turns[1:]  # Second turn

        common_ancestor = await branch_manager._find_common_ancestor(
            source_turns, target_turns
        )

        # Should return the ID of the last target turn
        assert common_ancestor == target_turns[-1]["id"]

    @pytest.mark.asyncio
    async def test_find_common_ancestor_no_target(self, branch_manager, sample_turns):
        """Test finding common ancestor when no target turns exist."""
        source_turns = sample_turns
        target_turns = []

        common_ancestor = await branch_manager._find_common_ancestor(
            source_turns, target_turns
        )

        # Should return "0" when no common ancestor
        assert common_ancestor == "0"

    @pytest.mark.asyncio
    async def test_merge_turns_append_strategy(self, branch_manager, sample_turns):
        """Test merging turns with append strategy."""
        target_turns = sample_turns[:1]
        source_turns = sample_turns[1:]

        merged_turns = await branch_manager._merge_turns(
            target_turns, source_turns, "append", "manual"
        )

        # Should append source turns to target turns
        assert len(merged_turns) == len(target_turns) + len(source_turns)
        assert merged_turns[: len(target_turns)] == target_turns
        assert merged_turns[len(target_turns) :] == source_turns

    @pytest.mark.asyncio
    async def test_merge_turns_interleave_strategy(self, branch_manager, sample_turns):
        """Test merging turns with interleave strategy."""
        # Create turns with different timestamps
        target_turns = [{**sample_turns[0], "created_at": datetime.utcnow()}]
        source_turns = [
            {**sample_turns[1], "created_at": datetime.utcnow() + timedelta(seconds=2)}
        ]

        merged_turns = await branch_manager._merge_turns(
            target_turns, source_turns, "interleave", "manual"
        )

        # Should interleave based on timestamps
        assert len(merged_turns) == len(target_turns) + len(source_turns)
        assert merged_turns[0] == target_turns[0]  # Earlier timestamp first
        assert merged_turns[1] == source_turns[0]  # Later timestamp second

    @pytest.mark.asyncio
    async def test_merge_turns_replace_strategy(self, branch_manager, sample_turns):
        """Test merging turns with replace strategy."""
        target_turns = sample_turns[:2]  # First two turns
        source_turns = sample_turns[2:]  # Remaining turns

        merged_turns = await branch_manager._merge_turns(
            target_turns, source_turns, "replace", "manual"
        )

        # Should replace last N target turns with source turns
        assert len(merged_turns) == len(target_turns)
        assert merged_turns[: -len(source_turns)] == target_turns[: -len(source_turns)]
        assert merged_turns[-len(source_turns) :] == source_turns

    @pytest.mark.asyncio
    async def test_merge_turns_unknown_strategy(self, branch_manager, sample_turns):
        """Test error with unknown merge strategy."""
        target_turns = sample_turns[:1]
        source_turns = sample_turns[1:]

        with pytest.raises(ValueError, match="Unknown merge strategy"):
            await branch_manager._merge_turns(
                target_turns, source_turns, "unknown", "manual"
            )

    @pytest.mark.asyncio
    async def test_merge_memory_files(
        self, branch_manager, mock_md_store, sample_memory_dir
    ):
        """Test merging memory files from source to target."""
        # Setup mocks
        branch_manager.md_store = mock_md_store

        source_session_id = str(uuid.uuid4())
        target_session_id = str(uuid.uuid4())

        # Mock memory directories
        mock_md_store.get_session_memory_dir.side_effect = lambda sid: sample_memory_dir

        # Test merge memory files
        await branch_manager._merge_memory_files(source_session_id, target_session_id)

        # Verify that files were merged (content should be doubled)
        for file_name in [
            "PROJECT.md",
            "LEARNED.md",
            "PREFERENCES.md",
            "FACTS.md",
            "DECISIONS.md",
        ]:
            file_path = sample_memory_dir / file_name
            content = file_path.read_text()
            # Content should contain separator indicating merge
            assert "---" in content
            assert content.count("# Content of") == 2  # Original + merged content

    @pytest.mark.asyncio
    async def test_merge_branches_success(
        self,
        branch_manager,
        mock_session_manager,
        mock_md_store,
        sample_session,
        sample_turns,
    ):
        """Test successful branch merging."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager
        branch_manager.md_store = mock_md_store

        source_session_id = str(uuid.uuid4())
        target_session_id = str(uuid.uuid4())

        mock_session_manager.get_session.side_effect = lambda sid: (
            sample_session
            if sid == target_session_id
            else {"id": source_session_id, "name": "source-branch"}
        )
        mock_session_manager.get_session_turns.return_value = sample_turns
        mock_session_manager.create_turn.return_value = None
        mock_session_manager.update_session_metadata.return_value = None

        mock_md_store.get_session_memory_dir.return_value = Path("/tmp/mock_memory")

        # Test merge branches
        result = await branch_manager.merge_branches(
            source_session_id=source_session_id,
            target_session_id=target_session_id,
            merge_strategy="append",
            conflict_resolution="manual",
        )

        # Verify results
        assert result["success"] is True
        assert result["source_session"] == "source-branch"
        assert result["target_session"] == sample_session["name"]
        assert result["merge_strategy"] == "append"
        assert len(result["merge_results"]) > 0

    @pytest.mark.asyncio
    async def test_get_merge_history(
        self, branch_manager, mock_session_manager, sample_session
    ):
        """Test getting merge history for a session."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager

        session_id = str(uuid.uuid4())
        sample_session["metadata"] = {
            "merge_history": [
                {
                    "source_session_id": str(uuid.uuid4()),
                    "merge_strategy": "append",
                    "merged_at": datetime.utcnow().isoformat(),
                    "merged_turns": 5,
                    "results": [],
                }
            ]
        }

        mock_session_manager.get_session.return_value = sample_session

        # Test get merge history
        history = await branch_manager.get_merge_history(session_id)

        # Verify results
        assert len(history) == 1
        assert history[0]["merge_strategy"] == "append"
        assert history[0]["merged_turns"] == 5

    @pytest.mark.asyncio
    async def test_get_merge_history_empty(
        self, branch_manager, mock_session_manager, sample_session
    ):
        """Test getting merge history when no history exists."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager

        session_id = str(uuid.uuid4())
        sample_session["metadata"] = {}  # No merge history

        mock_session_manager.get_session.return_value = sample_session

        # Test get merge history
        history = await branch_manager.get_merge_history(session_id)

        # Verify results
        assert len(history) == 0

    @pytest.mark.asyncio
    async def test_update_merge_metadata(
        self, branch_manager, mock_session_manager, sample_session
    ):
        """Test updating merge metadata for a session."""
        # Setup mocks
        branch_manager.session_manager = mock_session_manager

        session_id = str(uuid.uuid4())
        source_session_id = str(uuid.uuid4())

        mock_session_manager.get_session.return_value = sample_session
        mock_session_manager.update_session_metadata.return_value = None

        # Test update merge metadata
        await branch_manager._update_merge_metadata(
            target_session_id=session_id,
            source_session_id=source_session_id,
            strategy="append",
            results=[{"turn_id": str(uuid.uuid4()), "turn_number": 1}],
        )

        # Verify session manager calls
        mock_session_manager.update_session_metadata.assert_called_once()
        call_args = mock_session_manager.update_session_metadata.call_args
        assert call_args[0][0] == session_id
        assert "merge_history" in call_args[0][1]

    def test_branch_manager_initialization(self):
        """Test BranchManager initialization."""
        branch_manager = BranchManager()

        assert branch_manager.session_manager is not None
        assert branch_manager.md_store is not None

    @pytest.mark.asyncio
    async def test_branch_manager_with_real_dependencies(self):
        """Test BranchManager with real dependencies (integration test)."""
        # This test uses real dependencies but mocked database
        branch_manager = BranchManager()

        # Mock the session manager and MDStore to use test database
        with patch(
            "app.core.branch_manager.SessionManager"
        ) as mock_session_manager_class:
            with patch("app.core.branch_manager.get_md_store") as mock_get_md_store:
                mock_session_manager = AsyncMock()
                mock_md_store = AsyncMock()

                mock_session_manager_class.return_value = mock_session_manager
                mock_get_md_store.return_value = mock_md_store

                branch_manager.session_manager = mock_session_manager
                branch_manager.md_store = mock_md_store

                # Test basic functionality
                sample_session = {
                    "id": str(uuid.uuid4()),
                    "name": "test-session",
                    "created_at": datetime.utcnow(),
                    "status": "active",
                    "metadata": {},
                }

                mock_session_manager.get_session.return_value = sample_session
                mock_session_manager.get_session_turns.return_value = []
                mock_session_manager.create_session.return_value = None

                # This should not raise an exception
                try:
                    branch_id = await branch_manager.fork_session(
                        session_id=sample_session["id"]
                    )
                    assert isinstance(branch_id, str)
                except Exception as e:
                    # Expected when no turns exist
                    assert "No turns found" in str(e)
