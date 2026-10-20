"""
MVP phase: bootstrap verification tests.

Test M-00 project structure and FastAPI entry point.
"""


def test_app_imports():
    """Test that app.main can be imported."""
    from app.main import app

    assert app is not None


def test_health_endpoint(client):
    """Test /health endpoint returns 200 and expected response."""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert "message" in data
    assert "OryaAgent API is running" in data["message"]
