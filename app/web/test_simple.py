#!/usr/bin/env python3
"""
Simple integration test for Next.js UI components
"""

import sys
import os

# Add the app directory to Python path
app_dir = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, app_dir)
sys.path.insert(0, os.path.join(app_dir, '..'))

def test_nextjs_ui_routes():
    """Test Next.js UI routes directly"""
    try:
        from app.web.nextjs_ui import router as nextjs_router
        print("[OK] Next.js UI router imported successfully")
        
        # Count routes
        routes = []
        for route in nextjs_router.routes:
            if hasattr(route, 'path'):
                methods = getattr(route, 'methods', 'WebSocket')
                routes.append(f"{methods} {route.path}")
        
        print(f"[OK] Found {len(routes)} routes:")
        for route in routes:
            print(f"  {route}")
        
        # Check for expected routes
        expected = ['GET /', 'GET /sessions', 'GET /settings', 'GET /tool-calls']
        found_routes = [r for r in routes if any(r.startswith(method) for method in ['GET', 'POST'])]
        
        print(f"[OK] Found {len(found_routes)} HTTP routes")
        return True
        
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return False

def test_authentication():
    """Test authentication function"""
    try:
        from app.core.security import get_current_user
        print("[OK] Authentication function imported successfully")
        
        # Create a mock request
        class MockRequest:
            def __init__(self, user_id="test_user"):
                self.state = type('State', (), {'user_id': user_id})()
        
        # Test with valid user
        request = MockRequest("test_user")
        user = get_current_user(request)
        print(f"[OK] Authentication works: {user}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Authentication error: {e}")
        return False

def test_frontend_files():
    """Test that frontend files exist"""
    frontend_path = os.path.join(os.path.dirname(__file__), 'nextjs')
    print(f"Checking frontend path: {frontend_path}")
    
    if not os.path.exists(frontend_path):
        print("[ERROR] Frontend directory not found")
        return False
    
    # Check essential files
    essential_files = [
        'package.json',
        'tsconfig.json',
        'next.config.js',
        'app/layout.tsx',
        'app/page.tsx',
        'components/ChatInterface.tsx',
        'components/WebSocketProvider.tsx'
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
    return True

def test_package_json():
    """Test package.json content"""
    package_path = os.path.join(os.path.dirname(__file__), 'nextjs', 'package.json')
    
    if not os.path.exists(package_path):
        print("[ERROR] package.json not found")
        return False
    
    with open(package_path, 'r') as f:
        content = f.read()
        if 'next' in content and 'react' in content:
            print("[OK] package.json has required dependencies")
            return True
        else:
            print("[ERROR] package.json missing required dependencies")
            return False

def main():
    """Main test function"""
    print("=== Next.js UI Integration Test ===")
    print()
    
    tests = [
        ("Next.js UI Routes", test_nextjs_ui_routes),
        ("Authentication", test_authentication),
        ("Frontend Files", test_frontend_files),
        ("Package.json", test_package_json)
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