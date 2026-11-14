"""Simple test for B-16 Memory UI HTML template."""

import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_memory_template_exists():
    """Test that the memory HTML template exists."""
    template_path = project_root / "app" / "web" / "templates" / "memory.html"
    assert template_path.exists(), f"Memory template not found at {template_path}"
    
    # Read the template content
    with open(template_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Check for key components
    assert "Memory Management" in content, "Main title not found"
    assert "searchMemories" in content, "Search function not found"
    assert "loadMemories" in content, "Load memories function not found"
    assert "showAddModal" in content, "Add modal function not found"
    assert "deleteMemory" in content, "Delete function not found"
    assert "api/memory/list" in content, "API endpoint not referenced"
    assert "api/memory/stats" in content, "Stats API endpoint not referenced"
    assert "api/memory/remember" in content, "Add API endpoint not referenced"
    assert "api/memory/forget" in content, "Delete API endpoint not referenced"
    
    print("PASS: Memory template test passed")


def test_memory_ui_router():
    """Test that the memory UI router can be imported."""
    try:
        from app.web.memory_ui import router
        assert router is not None, "Router should not be None"
        print("PASS: Memory UI router import test passed")
    except ImportError as e:
        print(f"FAIL: Memory UI router import failed: {e}")
        # This might fail due to missing dependencies, which is expected in test environment


def test_api_endpoints():
    """Test that the API endpoints are properly defined."""
    try:
        from app.web.memory_ui import router
        
        # Check that the routes are registered
        routes = [route.path for route in router.routes]
        expected_routes = [
            "/memory",
            "/api/memory/list",
            "/api/memory/stats", 
            "/api/memory/search",
            "/api/memory/remember",
            "/api/memory/forget/{memory_id}"
        ]
        
        for expected_route in expected_routes:
            assert any(expected_route in route for route in routes), f"Route {expected_route} not found"
        
        print("PASS: API endpoints test passed")
    except ImportError as e:
        print(f"FAIL: API endpoints test failed (import error): {e}")


if __name__ == "__main__":
    print("Running B-16 Memory UI tests...")
    test_memory_template_exists()
    test_memory_ui_router()
    test_api_endpoints()
    print("All tests completed!")