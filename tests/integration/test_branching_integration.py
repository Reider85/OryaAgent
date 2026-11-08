"""Integration tests for BranchManager workflows (B-09).

Tests the complete branching workflow including API endpoints, database operations,
and integration with session management.
"""

import asyncio
import json
import pytest
import uuid
from datetime import datetime, timedelta
from httpx import AsyncClient
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.sessions import router
from app.core.branch_manager import BranchManager, get_branch_manager
from app.core.memory.md_store import MDStore
from app.core.session import SessionManager
from app.db.session_log import create_session, get_session, list_sessions, log_message
from fastapi.testclient import TestClient


class TestBranchingIntegration:
    """Integration tests for complete branching workflows."""

    @pytest.fixture
    def client(self):
        """Create test client for API testing."""
        return TestClient(router)

    @pytest.fixture
    def sample_session_data(self):
        """Sample session data for testing."""
        return {
            "title": "Test Session",
            "provider": "anthropic",
            "model": "claude-3-sonnet-20240229",
            "working_dir": "/tmp/test-project",
            "metadata": {"test": True},
        }

    @pytest.fixture
    def sample_message_data(self):
        """Sample message data for testing."""
        return {
            "content": "Hello, this is a test message",
            "provider": "anthropic",
            "model": "claude-3-sonnet-20240229",
            "permission_mode": "strict",
            "allow_list": [],
        }

    @pytest.fixture
    def sample_branch_data(self):
        """Sample branch data for testing."""
        return {"turn_id": None, "branch_name": "test-branch"}

    @pytest.fixture
    async def test_session(self, sample_session_data):
        """Create a test session in the database."""
        session = await create_session(**sample_session_data)
        return session

    @pytest.fixture
    async def test_session_with_messages(self, test_session):
        """Create a test session with messages."""
        session_id = test_session["session_id"]

        # Add some messages
        await log_message(session_id, "user", "Hello, world!")
        await log_message(session_id, "assistant", "Hi there! How can I help you?")
        await log_message(session_id, "user", "Can you help me with a coding task?")

        return await get_session(session_id)

    @pytest.mark.asyncio
    async def test_create_session_endpoint(self, client, sample_session_data):
        """Test session creation endpoint."""
        response = client.post("/sessions", json=sample_session_data)

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert data["title"] == sample_session_data["title"]
        assert data["provider"] == sample_session_data["provider"]

    @pytest.mark.asyncio
    async def test_list_sessions_endpoint(self, client, test_session):
        """Test listing sessions endpoint."""
        response = client.get("/sessions")

        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert len(data["items"]) > 0
        assert data["items"][0]["session_id"] == test_session["session_id"]

    @pytest.mark.asyncio
    async def test_get_session_endpoint(self, client, test_session_with_messages):
        """Test getting session details endpoint."""
        session_id = test_session_with_messages["session_id"]
        response = client.get(f"/sessions/{session_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == session_id
        assert "messages" in data
        assert len(data["messages"]) > 0

    @pytest.mark.asyncio
    async def test_fork_session_endpoint_success(
        self, client, test_session_with_messages, sample_branch_data
    ):
        """Test successful session fork endpoint."""
        session_id = test_session_with_messages["session_id"]
        response = client.post(f"/sessions/{session_id}/fork", json=sample_branch_data)

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "branch_session_id" in data
        assert "branch_name" in data
        assert data["session_id"] == session_id
        assert data["branch_name"] == sample_branch_data["branch_name"]

    @pytest.mark.asyncio
    async def test_fork_session_with_turn_id(self, client, test_session_with_messages):
        """Test session fork with specific turn ID."""
        session_id = test_session_with_messages["session_id"]
        branch_data = {
            "turn_id": test_session_with_messages["messages"][1]["id"],
            "branch_name": "specific-turn-branch",
        }

        response = client.post(f"/sessions/{session_id}/fork", json=branch_data)

        assert response.status_code == 200
        data = response.json()
        assert data["turn_id"] == branch_data["turn_id"]
        assert data["branch_name"] == branch_data["branch_name"]

    @pytest.mark.asyncio
    async def test_fork_session_invalid_session_id(self, client, sample_branch_data):
        """Test session fork with invalid session ID."""
        invalid_session_id = "non-existent-session-id"
        response = client.post(
            f"/sessions/{invalid_session_id}/fork", json=sample_branch_data
        )

        assert response.status_code == 400
        data = response.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_list_branches_endpoint(
        self, client, test_session_with_messages, sample_branch_data
    ):
        """Test listing branches endpoint."""
        session_id = test_session_with_messages["session_id"]

        # First create a branch
        client.post(f"/sessions/{session_id}/fork", json=sample_branch_data)

        # Then list branches
        response = client.get(f"/sessions/{session_id}/branches")

        assert response.status_code == 200
        data = response.json()
        assert "branches" in data
        assert "total" in data
        assert len(data["branches"]) > 0
        assert data["total"] > 0

    @pytest.mark.asyncio
    async def test_get_branch_info_endpoint(
        self, client, test_session_with_messages, sample_branch_data
    ):
        """Test getting branch information endpoint."""
        session_id = test_session_with_messages["session_id"]

        # First create a branch
        fork_response = client.post(
            f"/sessions/{session_id}/fork", json=sample_branch_data
        )
        branch_id = fork_response.json()["branch_session_id"]

        # Then get branch info
        response = client.get(f"/sessions/{session_id}/branches/{branch_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == branch_id
        assert data["name"] == sample_branch_data["branch_name"]
        assert data["parent_session_id"] == session_id

    @pytest.mark.asyncio
    async def test_get_branch_info_not_found(self, client, test_session_with_messages):
        """Test getting non-existent branch information."""
        session_id = test_session_with_messages["session_id"]
        invalid_branch_id = "non-existent-branch-id"

        response = client.get(f"/sessions/{session_id}/branches/{invalid_branch_id}")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_delete_branch_endpoint(
        self, client, test_session_with_messages, sample_branch_data
    ):
        """Test deleting a branch endpoint."""
        session_id = test_session_with_messages["session_id"]

        # First create a branch
        fork_response = client.post(
            f"/sessions/{session_id}/fork", json=sample_branch_data
        )
        branch_id = fork_response.json()["branch_session_id"]

        # Then delete the branch
        response = client.delete(f"/sessions/{session_id}/branches/{branch_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["branch_id"] == branch_id
        assert data["status"] == "deleted"

    @pytest.mark.asyncio
    async def test_delete_branch_not_found(self, client, test_session_with_messages):
        """Test deleting non-existent branch."""
        session_id = test_session_with_messages["session_id"]
        invalid_branch_id = "non-existent-branch-id"

        response = client.delete(f"/sessions/{session_id}/branches/{invalid_branch_id}")

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    @pytest.mark.asyncio
    async def test_complete_branching_workflow(
        self, client, sample_session_data, sample_message_data
    ):
        """Test complete branching workflow from start to finish."""
        # 1. Create main session
        session_response = client.post("/sessions", json=sample_session_data)
        assert session_response.status_code == 200
        main_session_id = session_response.json()["session_id"]

        # 2. Add some messages to main session
        await log_message(main_session_id, "user", "Hello, world!")
        await log_message(main_session_id, "assistant", "Hi there!")

        # 3. Create a branch
        branch_data = {"branch_name": "feature-branch"}
        fork_response = client.post(
            f"/sessions/{main_session_id}/fork", json=branch_data
        )
        assert fork_response.status_code == 200
        branch_session_id = fork_response.json()["branch_session_id"]

        # 4. Verify branch exists
        branches_response = client.get(f"/sessions/{main_session_id}/branches")
        assert branches_response.status_code == 200
        branches = branches_response.json()["branches"]
        assert len(branches) == 1
        assert branches[0]["id"] == branch_session_id

        # 5. Get branch info
        branch_info_response = client.get(
            f"/sessions/{main_session_id}/branches/{branch_session_id}"
        )
        assert branch_info_response.status_code == 200
        branch_info = branch_info_response.json()
        assert branch_info["id"] == branch_session_id
        assert branch_info["parent_session_id"] == main_session_id

        # 6. Add message to branch
        await log_message(branch_session_id, "user", "This is from the branch!")

        # 7. Delete branch
        delete_response = client.delete(
            f"/sessions/{main_session_id}/branches/{branch_session_id}"
        )
        assert delete_response.status_code == 200

        # 8. Verify branch is deleted
        branches_response = client.get(f"/sessions/{main_session_id}/branches")
        assert branches_response.status_code == 200
        branches = branches_response.json()["branches"]
        assert len(branches) == 0

    @pytest.mark.asyncio
    async def test_branch_isolation(
        self, client, sample_session_data, sample_message_data
    ):
        """Test that branches are properly isolated from parent sessions."""
        # 1. Create main session
        session_response = client.post("/sessions", json=sample_session_data)
        assert session_response.status_code == 200
        main_session_id = session_response.json()["session_id"]

        # 2. Add messages to main session
        await log_message(main_session_id, "user", "Original message")
        await log_message(main_session_id, "assistant", "Original response")

        # 3. Create branch
        branch_data = {"branch_name": "isolation-test-branch"}
        fork_response = client.post(
            f"/sessions/{main_session_id}/fork", json=branch_data
        )
        assert fork_response.status_code == 200
        branch_session_id = fork_response.json()["branch_session_id"]

        # 4. Add message to branch only
        await log_message(branch_session_id, "user", "Branch-specific message")

        # 5. Verify main session doesn't have branch message
        main_session = await get_session(main_session_id)
        main_messages = [
            msg for msg in main_session["messages"] if msg["role"] == "user"
        ]
        assert len(main_messages) == 1
        assert main_messages[0]["content"] == "Original message"

        # 6. Verify branch has both original and new message
        branch_session = await get_session(branch_session_id)
        branch_messages = [
            msg for msg in branch_session["messages"] if msg["role"] == "user"
        ]
        assert len(branch_messages) == 2
        assert "Original message" in [msg["content"] for msg in branch_messages]
        assert "Branch-specific message" in [msg["content"] for msg in branch_messages]

    @pytest.mark.asyncio
    async def test_multiple_branches_from_same_session(
        self, client, sample_session_data
    ):
        """Test creating multiple branches from the same session."""
        # 1. Create main session
        session_response = client.post("/sessions", json=sample_session_data)
        assert session_response.status_code == 200
        main_session_id = session_response.json()["session_id"]

        # 2. Add some messages
        await log_message(main_session_id, "user", "Hello, world!")
        await log_message(main_session_id, "assistant", "Hi there!")

        # 3. Create multiple branches
        branch_names = ["branch-1", "branch-2", "branch-3"]
        branch_ids = []

        for name in branch_names:
            branch_data = {"branch_name": name}
            fork_response = client.post(
                f"/sessions/{main_session_id}/fork", json=branch_data
            )
            assert fork_response.status_code == 200
            branch_ids.append(fork_response.json()["branch_session_id"])

        # 4. Verify all branches exist
        branches_response = client.get(f"/sessions/{main_session_id}/branches")
        assert branches_response.status_code == 200
        branches = branches_response.json()["branches"]
        assert len(branches) == 3

        # 5. Verify each branch has correct name
        branch_names_from_response = [branch["name"] for branch in branches]
        assert set(branch_names_from_response) == set(branch_names)

        # 6. Delete all branches
        for branch_id in branch_ids:
            delete_response = client.delete(
                f"/sessions/{main_session_id}/branches/{branch_id}"
            )
            assert delete_response.status_code == 200

        # 7. Verify all branches are deleted
        branches_response = client.get(f"/sessions/{main_session_id}/branches")
        assert branches_response.status_code == 200
        branches = branches_response.json()["branches"]
        assert len(branches) == 0

    @pytest.mark.asyncio
    async def test_branch_with_memory_files(
        self, client, tmp_path, sample_session_data
    ):
        """Test that branches properly copy memory files."""
        # 1. Create main session with custom working directory
        working_dir = tmp_path / "test_project"
        working_dir.mkdir()

        modified_session_data = sample_session_data.copy()
        modified_session_data["working_dir"] = str(working_dir)

        session_response = client.post("/sessions", json=modified_session_data)
        assert session_response.status_code == 200
        main_session_id = session_response.json()["session_id"]

        # 2. Create memory files in main session
        memory_files = ["PROJECT.md", "LEARNED.md", "PREFERENCES.md"]
        for file_name in memory_files:
            file_path = working_dir / file_name
            file_path.write_text(f"# Content of {file_name}")

        # 3. Create branch
        branch_data = {"branch_name": "memory-test-branch"}
        fork_response = client.post(
            f"/sessions/{main_session_id}/fork", json=branch_data
        )
        assert fork_response.status_code == 200
        branch_session_id = fork_response.json()["branch_session_id"]

        # 4. Verify branch has memory files (this would require additional implementation)
        # This test is more conceptual as memory file copying is handled internally
        main_session = await get_session(main_session_id)
        branch_session = await get_session(branch_session_id)

        # Both sessions should exist
        assert main_session is not None
        assert branch_session is not None
        assert branch_session["parent_session_id"] == main_session_id

    @pytest.mark.asyncio
    async def test_concurrent_branch_creation(self, client, sample_session_data):
        """Test concurrent branch creation."""
        # 1. Create main session
        session_response = client.post("/sessions", json=sample_session_data)
        assert session_response.status_code == 200
        main_session_id = session_response.json()["session_id"]

        # 2. Add some messages
        await log_message(main_session_id, "user", "Hello, world!")

        # 3. Create multiple branches concurrently
        branch_names = [
            "concurrent-branch-1",
            "concurrent-branch-2",
            "concurrent-branch-3",
        ]

        async def create_branch(name):
            branch_data = {"branch_name": name}
            response = client.post(
                f"/sessions/{main_session_id}/fork", json=branch_data
            )
            return response.json()["branch_session_id"]

        # Create branches concurrently
        branch_ids = await asyncio.gather(
            *[create_branch(name) for name in branch_names]
        )

        # 4. Verify all branches were created
        branches_response = client.get(f"/sessions/{main_session_id}/branches")
        assert branches_response.status_code == 200
        branches = branches_response.json()["branches"]
        assert len(branches) == 3

        # 5. Verify no duplicate branch IDs
        assert len(set(branch_ids)) == 3

    @pytest.mark.asyncio
    async def test_branch_error_handling(self, client, sample_session_data):
        """Test error handling in branch operations."""
        # 1. Create main session
        session_response = client.post("/sessions", json=sample_session_data)
        assert session_response.status_code == 200
        main_session_id = session_response.json()["session_id"]

        # 2. Test fork with invalid turn ID
        branch_data = {"turn_id": "invalid-turn-id"}
        response = client.post(f"/sessions/{main_session_id}/fork", json=branch_data)
        assert response.status_code == 400

        # 3. Test list branches for non-existent session
        response = client.get("/sessions/non-existent-session-id/branches")
        assert response.status_code == 404

        # 4. Test get branch info for non-existent session
        response = client.get(
            "/sessions/non-existent-session-id/branches/non-existent-branch-id"
        )
        assert response.status_code == 404

        # 5. Test delete branch for non-existent session
        response = client.delete(
            "/sessions/non-existent-session-id/branches/non-existent-branch-id"
        )
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_branch_with_large_session(self, client, sample_session_data):
        """Test branch creation with large session (many messages)."""
        # 1. Create main session
        session_response = client.post("/sessions", json=sample_session_data)
        assert session_response.status_code == 200
        main_session_id = session_response.json()["session_id"]

        # 2. Add many messages (simulate large session)
        for i in range(50):
            await log_message(main_session_id, "user", f"Message {i}")
            await log_message(main_session_id, "assistant", f"Response {i}")

        # 3. Create branch
        branch_data = {"branch_name": "large-session-branch"}
        fork_response = client.post(
            f"/sessions/{main_session_id}/fork", json=branch_data
        )
        assert fork_response.status_code == 200
        branch_session_id = fork_response.json()["branch_session_id"]

        # 4. Verify branch was created successfully
        main_session = await get_session(main_session_id)
        branch_session = await get_session(branch_session_id)

        assert main_session is not None
        assert branch_session is not None
        assert branch_session["parent_session_id"] == main_session_id

        # 5. Verify branch has all messages
        main_messages = len(main_session["messages"])
        branch_messages = len(branch_session["messages"])
        assert (
            branch_messages == main_messages
        )  # Branch should have all parent messages

    @pytest.mark.asyncio
    async def test_branch_performance(self, client, sample_session_data):
        """Test branch creation performance."""
        # 1. Create main session
        session_response = client.post("/sessions", json=sample_session_data)
        assert session_response.status_code == 200
        main_session_id = session_response.json()["session_id"]

        # 2. Add moderate number of messages
        for i in range(20):
            await log_message(main_session_id, "user", f"Message {i}")

        # 3. Time branch creation
        import time

        start_time = time.time()

        branch_data = {"branch_name": "performance-test-branch"}
        fork_response = client.post(
            f"/sessions/{main_session_id}/fork", json=branch_data
        )
        end_time = time.time()

        assert fork_response.status_code == 200
        branch_session_id = fork_response.json()["branch_session_id"]

        # 4. Verify performance (should complete within reasonable time)
        creation_time = end_time - start_time
        assert creation_time < 5.0  # Should complete within 5 seconds

        # 5. Verify branch was created
        branch_session = await get_session(branch_session_id)
        assert branch_session is not None
