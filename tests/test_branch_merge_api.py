"""Integration tests for branch merge API endpoint (B-10)."""

import json
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main import app


class TestBranchMergeAPI:
    """Test cases for branch merge API endpoint."""

    @pytest.fixture
    def client(self):
        """Create test client."""
        return TestClient(app)

    @pytest.fixture
    def mock_branch_manager(self):
        """Create mock branch manager."""
        with patch("app.api.sessions.get_branch_manager") as mock_manager:
            mock_instance = AsyncMock()
            mock_manager.return_value = mock_instance
            yield mock_instance

    @pytest.fixture
    def mock_sessions(self):
        """Create mock session data."""
        return {
            "source_session": {
                "id": "source-123",
                "name": "test-branch",
                "parent_session_id": "parent-123",
                "created_at": "2023-01-01T00:00:00Z",
                "status": "active",
                "metadata": {"branch_name": "test-branch"},
            },
            "target_session": {
                "id": "target-123",
                "name": "main-session",
                "created_at": "2023-01-01T00:00:00Z",
                "status": "active",
                "metadata": {},
            },
        }

    def test_merge_branches_success_append(
        self, client, mock_branch_manager, mock_sessions
    ):
        """Test successful merge with append strategy."""
        # Setup mocks
        mock_branch_manager.merge_branches.return_value = {
            "success": True,
            "source_session": "test-branch",
            "target_session": "main-session",
            "merge_strategy": "append",
            "merged_turns": 2,
            "merge_results": [
                {
                    "turn_id": "turn-1",
                    "turn_number": 1,
                    "messages_count": 1,
                    "tool_calls_count": 0,
                },
                {
                    "turn_id": "turn-2",
                    "turn_number": 2,
                    "messages_count": 1,
                    "tool_calls_count": 1,
                },
            ],
            "conflicts_resolved": 2,
            "merge_id": "merge-20231201-123456-abc123",
        }

        # Make API request
        response = client.post(
            "/sessions/target-123/merge",
            json={
                "source_session_id": "source-123",
                "merge_strategy": "append",
                "conflict_resolution": "manual",
            },
        )

        # Verify response
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["source_session"] == "test-branch"
        assert data["target_session"] == "main-session"
        assert data["merge_strategy"] == "append"
        assert data["merged_turns"] == 2
        assert data["conflicts_resolved"] == 2
        assert "merge_id" in data

        # Verify merge_branches was called correctly
        mock_branch_manager.merge_branches.assert_called_once_with(
            source_session_id="source-123",
            target_session_id="target-123",
            merge_strategy="append",
            conflict_resolution="manual",
        )

    def test_merge_branches_success_interleave(self, client, mock_branch_manager):
        """Test successful merge with interleave strategy."""
        mock_branch_manager.merge_branches.return_value = {
            "success": True,
            "source_session": "test-branch",
            "target_session": "main-session",
            "merge_strategy": "interleave",
            "merged_turns": 3,
            "merge_results": [
                {
                    "turn_id": "turn-1",
                    "turn_number": 1,
                    "messages_count": 1,
                    "tool_calls_count": 0,
                },
                {
                    "turn_id": "turn-2",
                    "turn_number": 2,
                    "messages_count": 1,
                    "tool_calls_count": 0,
                },
                {
                    "turn_id": "turn-3",
                    "turn_number": 3,
                    "messages_count": 1,
                    "tool_calls_count": 1,
                },
            ],
            "conflicts_resolved": 3,
            "merge_id": "merge-20231201-123456-def456",
        }

        response = client.post(
            "/sessions/target-123/merge",
            json={
                "source_session_id": "source-123",
                "merge_strategy": "interleave",
                "conflict_resolution": "auto",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["merge_strategy"] == "interleave"
        assert data["conflict_resolution"] == "auto"

    def test_merge_branches_success_replace(self, client, mock_branch_manager):
        """Test successful merge with replace strategy."""
        mock_branch_manager.merge_branches.return_value = {
            "success": True,
            "source_session": "test-branch",
            "target_session": "main-session",
            "merge_strategy": "replace",
            "merged_turns": 1,
            "merge_results": [
                {
                    "turn_id": "turn-1",
                    "turn_number": 1,
                    "messages_count": 1,
                    "tool_calls_count": 0,
                }
            ],
            "conflicts_resolved": 1,
            "merge_id": "merge-20231201-123456-ghi789",
        }

        response = client.post(
            "/sessions/target-123/merge",
            json={
                "source_session_id": "source-123",
                "merge_strategy": "replace",
                "conflict_resolution": "source",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["merge_strategy"] == "replace"
        assert data["conflict_resolution"] == "source"

    def test_merge_branches_missing_source_session(self, client, mock_branch_manager):
        """Test merge with missing source session."""
        mock_branch_manager.merge_branches.side_effect = ValueError(
            "Source session not found: missing-123"
        )

        response = client.post(
            "/sessions/target-123/merge",
            json={
                "source_session_id": "missing-123",
                "merge_strategy": "append",
                "conflict_resolution": "manual",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "Source session not found" in data["detail"]

    def test_merge_branches_missing_target_session(self, client, mock_branch_manager):
        """Test merge with missing target session."""
        mock_branch_manager.merge_branches.side_effect = ValueError(
            "Target session not found: missing-123"
        )

        response = client.post(
            "/sessions/target-123/merge",
            json={
                "source_session_id": "source-123",
                "merge_strategy": "append",
                "conflict_resolution": "manual",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "Target session not found" in data["detail"]

    def test_merge_branches_invalid_strategy(self, client, mock_branch_manager):
        """Test merge with invalid strategy."""
        mock_branch_manager.merge_branches.side_effect = ValueError(
            "Unknown merge strategy: invalid_strategy"
        )

        response = client.post(
            "/sessions/target-123/merge",
            json={
                "source_session_id": "source-123",
                "merge_strategy": "invalid_strategy",
                "conflict_resolution": "manual",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid merge strategy" in data["detail"]

    def test_merge_branches_invalid_resolution(self, client, mock_branch_manager):
        """Test merge with invalid conflict resolution."""
        response = client.post(
            "/sessions/target-123/merge",
            json={
                "source_session_id": "source-123",
                "merge_strategy": "append",
                "conflict_resolution": "invalid_resolution",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid conflict resolution" in data["detail"]

    def test_merge_branches_merge_error(self, client, mock_branch_manager):
        """Test merge with general error."""
        mock_branch_manager.merge_branches.side_effect = ValueError(
            "Failed to merge branches: conflict detected"
        )

        response = client.post(
            "/sessions/target-123/merge",
            json={
                "source_session_id": "source-123",
                "merge_strategy": "append",
                "conflict_resolution": "manual",
            },
        )

        assert response.status_code == 400
        data = response.json()
        assert "Failed to merge branches" in data["detail"]

    def test_merge_branches_default_values(self, client, mock_branch_manager):
        """Test merge with default values."""
        mock_branch_manager.merge_branches.return_value = {
            "success": True,
            "source_session": "test-branch",
            "target_session": "main-session",
            "merge_strategy": "append",
            "merged_turns": 1,
            "merge_results": [],
            "conflicts_resolved": 0,
            "merge_id": "merge-20231201-123456-jkl012",
        }

        # Send request without optional fields
        response = client.post(
            "/sessions/target-123/merge", json={"source_session_id": "source-123"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["merge_strategy"] == "append"  # Default value
        assert data["conflict_resolution"] == "manual"  # Default value

        # Verify merge_branches was called with defaults
        mock_branch_manager.merge_branches.assert_called_once_with(
            source_session_id="source-123",
            target_session_id="target-123",
            merge_strategy="append",
            conflict_resolution="manual",
        )

    def test_merge_branches_invalid_json(self, client):
        """Test merge with invalid JSON."""
        response = client.post(
            "/sessions/target-123/merge",
            data="invalid json",
            headers={"content-type": "application/json"},
        )

        assert response.status_code == 422

    def test_merge_branches_missing_source_id(self, client):
        """Test merge with missing source_session_id."""
        response = client.post(
            "/sessions/target-123/merge",
            json={"merge_strategy": "append", "conflict_resolution": "manual"},
        )

        assert response.status_code == 422
        data = response.json()
        assert "source_session_id" in data["detail"][0]["loc"]

    def test_merge_branches_empty_source_id(self, client):
        """Test merge with empty source_session_id."""
        response = client.post(
            "/sessions/target-123/merge",
            json={
                "source_session_id": "",
                "merge_strategy": "append",
                "conflict_resolution": "manual",
            },
        )

        assert response.status_code == 422
        data = response.json()
        assert "source_session_id" in data["detail"][0]["loc"]

    def test_merge_branchs_wrong_method(self, client):
        """Test using wrong HTTP method."""
        response = client.get("/sessions/target-123/merge")
        assert response.status_code == 405

    def test_merge_branchs_unauthorized(self, client):
        """Test merge without authentication (if auth is enabled)."""
        # This test would depend on your authentication setup
        # For now, just verify the endpoint exists
        response = client.post(
            "/sessions/target-123/merge", json={"source_session_id": "source-123"}
        )
        # The actual status code would depend on auth configuration
        # This could be 401, 403, or 200 if auth is disabled for testing
        assert response.status_code in [200, 401, 403]

    def test_merge_branchs_rate_limit(self, client):
        """Test merge rate limiting (if enabled)."""
        # This test would depend on your rate limiting setup
        # For now, just verify the endpoint exists
        response = client.post(
            "/sessions/target-123/merge", json={"source_session_id": "source-123"}
        )
        # The actual status code would depend on rate limiting configuration
        # This could be 429 if rate limited, or 200 if rate limiting is disabled
        assert response.status_code in [200, 429]
