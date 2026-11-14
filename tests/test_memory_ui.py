"""Test for B-16 Memory UI functionality."""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_memory_management_page():
    """Test that the memory management page loads."""
    response = client.get("/memory")
    assert response.status_code == 200
    assert "Memory Management" in response.text


def test_memory_list_endpoint():
    """Test the memory list API endpoint."""
    response = client.get("/api/memory/list?session_id=test_session")
    assert response.status_code == 200
    data = response.json()
    assert "memories" in data


def test_memory_stats_endpoint():
    """Test the memory stats API endpoint."""
    response = client.get("/api/memory/stats?session_id=test_session")
    assert response.status_code == 200
    data = response.json()
    assert "total_memories" in data
    assert "average_content_length" in data


def test_memory_search_endpoint():
    """Test the memory search API endpoint."""
    response = client.post("/api/memory/search", json={
        "query": "test",
        "session_id": "test_session",
        "limit": 10
    })
    assert response.status_code == 200
    data = response.json()
    assert "memories" in data


def test_memory_add_endpoint():
    """Test adding a new memory."""
    response = client.post("/api/memory/remember", json={
        "session_id": "test_session",
        "content": "Test memory content",
        "metadata": {"source": "test", "type": "fact"}
    })
    assert response.status_code == 200
    data = response.json()
    assert "id" in data
    assert "message" in data


def test_memory_delete_endpoint():
    """Test deleting a memory."""
    # First add a memory to delete
    add_response = client.post("/api/memory/remember", json={
        "session_id": "test_session",
        "content": "Memory to delete",
        "metadata": {"source": "test", "type": "deletable"}
    })
    memory_id = add_response.json()["id"]
    
    # Then delete it
    response = client.delete(f"/api/memory/forget/{memory_id}?session_id=test_session")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data
    assert "memory_id" in data