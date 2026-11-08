#!/usr/bin/env python3
"""
Test script to verify Next.js UI integration with main application
"""

import sys
import os

# Add the app directory to Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_main_app_routes():
    """Test that main application includes Next.js UI routes"""
    try:
        from app.main import app

        print("✓ Main application imported successfully")

        # Find Next.js UI routes
        nextjs_routes = []
        for route in app.routes:
            if hasattr(route, "path") and "/web/" in route.path:
                methods = getattr(route, "methods", "WebSocket")
                nextjs_routes.append(f"{methods} {route.path}")

        if nextjs_routes:
            print(f"✓ Found {len(nextjs_routes)} Next.js UI routes:")
            for route in nextjs_routes:
                print(f"  {route}")
            return True
        else:
            print("[ERROR] No Next.js UI routes found")
            return False

    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return False


def test_nextjs_ui_router():
    """Test that Next.js UI router can be imported independently"""
    try:
        from app.web.nextjs_ui import router as nextjs_router

        print("✓ Next.js UI router imported successfully")

        # Count routes
        http_routes = []
        for route in nextjs_router.routes:
            if hasattr(route, "path") and hasattr(route, "methods"):
                http_routes.append(f"{route.methods} {route.path}")

        print(f"✓ Found {len(http_routes)} HTTP routes:")
        for route in http_routes:
            print(f"  {route}")

        return True

    except Exception as e:
        print(f"[ERROR] Error importing Next.js UI router: {e}")
        return False


def test_authentication_function():
    """Test that authentication function works"""
    try:
        from app.core.security import get_current_user

        print("✓ Authentication function imported successfully")

        # Create a mock request
        class MockRequest:
            def __init__(self, user_id="test_user"):
                self.state = type("State", (), {"user_id": user_id})()

        # Test with valid user
        request = MockRequest("test_user")
        user = get_current_user(request)
        print(f"✓ Authentication works: {user}")

        # Test with no user
        bad_request = MockRequest()
        del bad_request.state.user_id
        try:
            get_current_user(bad_request)
            print("✗ Should have raised exception for missing user")
            return False
        except Exception:
            print("✓ Properly handles missing user")

        return True

    except Exception as e:
        print(f"[ERROR] Authentication error: {e}")
        return False


def test_frontend_files():
    """Test that frontend files exist and are properly structured"""
    frontend_path = os.path.join(os.path.dirname(__file__), "..", "nextjs")

    if not os.path.exists(frontend_path):
        print("[ERROR] Frontend directory not found")
        return False

    # Check essential files
    essential_files = [
        "package.json",
        "tsconfig.json",
        "next.config.js",
        "app/layout.tsx",
        "app/page.tsx",
        "components/ChatInterface.tsx",
        "components/WebSocketProvider.tsx",
    ]

    missing_files = []
    for file in essential_files:
        file_path = os.path.join(frontend_path, file)
        if not os.path.exists(file_path):
            missing_files.append(file)

    if missing_files:
        print(f"[ERROR] Missing files: {missing_files}")
        return False

    print("[OK] All essential frontend files found")

    # Check package.json content
    package_path = os.path.join(frontend_path, "package.json")
    with open(package_path, "r") as f:
        package_content = f.read()
        if "next" in package_content and "react" in package_content:
            print("✓ package.json has required dependencies")
        else:
            print("[ERROR] package.json missing required dependencies")
            return False

    return True


def main():
    """Main test function"""
    print("=== Next.js UI Integration Test ===")
    print()

    tests = [
        ("Main App Routes", test_main_app_routes),
        ("Next.js UI Router", test_nextjs_ui_router),
        ("Authentication", test_authentication_function),
        ("Frontend Files", test_frontend_files),
    ]

    results = []
    for test_name, test_func in tests:
        print(f"Running {test_name}...")
        result = test_func()
        results.append((test_name, result))
        print()

    print("=== Test Results ===")
    passed = 0
    for test_name, result in results:
        status = "PASS" if result else "FAIL"
        print(f"{test_name}: {status}")
        if result:
            passed += 1

    print(f"\nPassed: {passed}/{len(tests)}")

    if passed == len(tests):
        print("[OK] All integration tests passed!")
    else:
        print("[ERROR] Some integration tests failed")


if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
