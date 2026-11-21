#!/usr/bin/env python3
"""
Test script for B-20 Hooks UI implementation.

This script verifies that the hooks audit log UI is properly implemented
and integrated with the existing hooks framework.
"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_hooks_api():
    """Test the hooks API endpoints."""
    print("Testing hooks API endpoints...")

    try:
        from app.api.hooks import router

        print("SUCCESS: Hooks API router imported successfully")

        # Check if the endpoints exist
        routes = [route.path for route in router.routes]
        expected_endpoints = [
            "/hooks/executed",
            "/hooks/registry",
            "/hooks/statistics",
            "/hooks/csv",
        ]

        for endpoint in expected_endpoints:
            if endpoint in routes:
                print(f"SUCCESS: Endpoint {endpoint} exists")
            else:
                print(f"ERROR: Endpoint {endpoint} missing")

    except Exception as e:
        print(f"ERROR: Error testing hooks API: {e}")


def test_hooks_ui():
    """Test the hooks UI templates."""
    print("\nTesting hooks UI templates...")

    templates_dir = project_root / "app" / "web" / "templates" / "hooks"

    expected_templates = [
        "hooks.html",
        "execution-log.html",
        "detail.html",
        "statistics.html",
    ]

    for template in expected_templates:
        template_path = templates_dir / template
        if template_path.exists():
            print(f"SUCCESS: Template {template} exists")
        else:
            print(f"ERROR: Template {template} missing")

    # Also check if base template exists
    base_template = project_root / "app" / "web" / "templates" / "base.html"
    if base_template.exists():
        print("SUCCESS: Base template exists")
    else:
        print("ERROR: Base template missing")


def test_hooks_ui_routes():
    """Test the hooks UI routes."""
    print("\nTesting hooks UI routes...")

    try:
        from app.web.hooks_ui import router

        print("SUCCESS: Hooks UI router imported successfully")

        # Check if the routes exist
        routes = [route.path for route in router.routes]
        expected_routes = [
            "/ui/hooks/",
            "/ui/hooks/execution-log",
            "/ui/hooks/detail/{hook_name}",
            "/ui/hooks/statistics",
        ]

        for route in expected_routes:
            if route in routes:
                print(f"SUCCESS: Route {route} exists")
            else:
                print(f"ERROR: Route {route} missing")

    except Exception as e:
        print(f"ERROR: Error testing hooks UI routes: {e}")


def test_base_template():
    """Test the base template."""
    print("\nTesting base template...")

    base_template = project_root / "app" / "web" / "templates" / "base.html"

    if base_template.exists():
        print("SUCCESS: Base template exists")

        # Check if it contains hooks navigation
        with open(base_template) as f:
            content = f.read()
            if 'href="/ui/hooks/"' in content:
                print("SUCCESS: Hooks navigation included in base template")
            else:
                print("ERROR: Hooks navigation missing from base template")
    else:
        print("ERROR: Base template missing")


def main():
    """Main test function."""
    print("=== B-20 Hooks UI Implementation Test ===\n")

    # Test components
    test_hooks_api()
    test_hooks_ui()
    test_hooks_ui_routes()
    test_base_template()

    print("\n=== Test Complete ===")
    print("\nTo run the application with the new Hooks UI:")
    print("1. Start the FastAPI server: uvicorn app.main:app --reload")
    print("2. Access the Hooks UI at: http://localhost:8000/ui/hooks/")
    print("3. Test the different views:")
    print("   - Main audit log: /ui/hooks/")
    print("   - Execution log: /ui/hooks/execution-log")
    print("   - Statistics: /ui/hooks/statistics")
    print("   - Hook details: /ui/hooks/detail/{hook_name}")


if __name__ == "__main__":
    main()
