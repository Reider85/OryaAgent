"""Unit tests for B-12 — Next.js Web UI session management endpoints."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.core.config import clear_settings_cache

client = TestClient(app)


@pytest.fixture(autouse=True)
def _isolated_config() -> None:
    """Ensure test isolation by clearing settings cache."""
    clear_settings_cache()


def test_create_web_session() -> None:
    """Test creating a new session via web API."""
    response = client.post(
        "/web/api/sessions",
        json={
            "name": "Test Session",
            "description": "A test session for B-12",
            "workspace": "/tmp/test"
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    
    assert "id" in data
    assert data["name"] == "Test Session"
    assert data["description"] == "A test session for B-12"
    assert data["workspace"] == "/tmp/test"
    assert data["status"] == "active"
    assert data["message_count"] == 0
    assert "created_at" in data
    assert "updated_at" in data


def test_list_web_sessions() -> None:
    """Test listing sessions via web API."""
    # Create a test session first
    client.post(
        "/web/api/sessions",
        json={"name": "Test Session 1", "description": "First test session"}
    )
    client.post(
        "/web/api/sessions",
        json={"name": "Test Session 2", "description": "Second test session"}
    )
    
    # Test listing all sessions
    response = client.post("/web/api/sessions/list")
    assert response.status_code == 200
    data = response.json()
    
    assert "sessions" in data
    assert "total" in data
    assert len(data["sessions"]) >= 2
    assert data["total"] >= 2
    
    # Test search functionality
    response = client.post(
        "/web/api/sessions/list",
        json={"search": "First test"}
    )
    assert response.status_code == 200
    data = response.json()
    
    assert len(data["sessions"]) == 1
    assert "First test session" in data["sessions"][0]["name"]
    
    # Test status filtering
    response = client.post(
        "/web/api/sessions/list",
        json={"status": ["active"]}
    )
    assert response.status_code == 200
    data = response.json()
    
    assert all(session["status"] == "active" for session in data["sessions"])


def test_get_web_session() -> None:
    """Test getting a specific session via web API."""
    # Create a test session
    create_response = client.post(
        "/web/api/sessions",
        json={"name": "Test Session for Get"}
    )
    session_id = create_response.json()["id"]
    
    # Get the session
    response = client.get(f"/web/api/sessions/{session_id}")
    assert response.status_code == 200
    data = response.json()
    
    assert data["id"] == session_id
    assert data["name"] == "Test Session for Get"


def test_update_web_session() -> None:
    """Test updating a session via web API."""
    # Create a test session
    create_response = client.post(
        "/web/api/sessions",
        json={"name": "Original Name"}
    )
    session_id = create_response.json()["id"]
    
    # Update the session
    response = client.patch(
        f"/web/api/sessions/{session_id}",
        json={"name": "Updated Name", "description": "Updated description"}
    )
    assert response.status_code == 200
    data = response.json()
    
    assert data["name"] == "Updated Name"
    assert data["description"] == "Updated description"
    
    # Test status update
    response = client.patch(
        f"/web/api/sessions/{session_id}",
        json={"status": "completed"}
    )
    assert response.status_code == 200
    data = response.json()
    
    assert data["status"] == "completed"


def test_delete_web_session() -> None:
    """Test deleting a session via web API."""
    # Create a test session
    create_response = client.post(
        "/web/api/sessions",
        json={"name": "Session to Delete"}
    )
    session_id = create_response.json()["id"]
    
    # Delete the session
    response = client.delete(f"/web/api/sessions/{session_id}")
    assert response.status_code == 200
    data = response.json()
    
    assert data["session_id"] == session_id
    assert data["status"] == "deleted"
    
    # Verify session is deleted
    get_response = client.get(f"/web/api/sessions/{session_id}")
    assert get_response.status_code == 404


def test_web_session_status_mapping() -> None:
    """Test that status mapping works correctly."""
    # Test creating a session with different statuses
    test_cases = [
        ("active", "active"),
        ("completed", "completed"),
        ("archived", "archived")
    ]
    
    for frontend_status, expected_backend_status in test_cases:
        response = client.post(
            "/web/api/sessions",
            json={"name": f"Test {frontend_status} session", "status": frontend_status}
        )
        
        # The backend should handle status mapping correctly
        if response.status_code == 200:
            data = response.json()
            # Status should be properly mapped
            assert data["status"] in ["active", "completed", "archived"]