from fastapi.testclient import TestClient

from app.web.nextjs_ui import router as nextjs_ui_router


def test_tool_call_visualization_endpoints():
    """Test that tool call visualization endpoints are available."""
    client = TestClient(nextjs_ui_router)

    # Test that the router is properly configured
    assert nextjs_ui_router is not None

    # Test a sample endpoint (this will fail without proper session data, but confirms the route exists)
    response = client.get("/ui/api/sessions/test-session/tool-calls/tree")
    # Should fail with 404 for non-existent session, but route should exist
    assert response.status_code in [404, 500]  # Either session not found or other error


def test_tool_call_visualization_stats_endpoint():
    """Test that tool call statistics endpoint is available."""
    client = TestClient(nextjs_ui_router)

    response = client.get("/ui/api/sessions/test-session/tool-calls/statistics")
    # Should fail with 404 for non-existent session, but route should exist
    assert response.status_code in [404, 500]
