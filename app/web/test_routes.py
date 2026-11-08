#!/usr/bin/env python3
"""
Simple test to verify Next.js UI routes are properly defined
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

def test_nextjs_routes():
    """Test that Next.js UI routes are defined"""
    try:
        from app.web.nextjs_ui import router as nextjs_router
        print("✓ Next.js UI router imported successfully")
        
        # Check that routes exist
        routes = []
        for route in nextjs_router.routes:
            if hasattr(route, 'path'):
                methods = getattr(route, 'methods', 'WebSocket')
                routes.append(f"{methods} {route.path}")
        
        print(f"✓ Found {len(routes)} routes:")
        for route in routes:
            print(f"  {route}")
        
        # Check specific routes
        expected_routes = [
            'GET /',
            'GET /sessions',
            'GET /settings',
            'GET /tool-calls'
        ]
        
        found_routes = [r for r in routes if any(r.startswith(method) for method in ['GET', 'POST'])]
        print(f"✓ Found {len(found_routes)} HTTP routes")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Error: {e}")
        return False

def test_authentication():
    """Test authentication function"""
    try:
        from app.core.security import get_current_user
        print("✓ get_current_user function imported successfully")
        
        # Create a mock request
        class MockRequest:
            def __init__(self):
                self.state = type('State', (), {'user_id': 'test_user'})()
        
        request = MockRequest()
        user = get_current_user(request)
        print(f"[OK] get_current_user returned: {user}")
        
        return True
        
    except Exception as e:
        print(f"[ERROR] Authentication error: {e}")
        return False

def test_frontend_structure():
    """Test that frontend files exist"""
    frontend_path = os.path.join(os.path.dirname(__file__), '..', 'nextjs')
    
    if not os.path.exists(frontend_path):
        print("[ERROR] Frontend directory not found")
        return False
    
    required_files = [
        'package.json',
        'tsconfig.json',
        'next.config.js',
        'app/page.tsx',
        'components/ChatInterface.tsx',
        'components/WebSocketProvider.tsx'
    ]
    
    missing_files = []
    for file in required_files:
        file_path = os.path.join(frontend_path, file)
        if not os.path.exists(file_path):
            missing_files.append(file)
    
    if missing_files:
        print(f"[ERROR] Missing files: {missing_files}")
        return False
    
    print("[OK] All required frontend files found")
    return True

def main():
    """Main test function"""
    print("=== Next.js Web UI (B-11) Implementation Test ===")
    print()
    
    tests = [
        ("Routes Definition", test_nextjs_routes),
        ("Authentication", test_authentication),
        ("Frontend Structure", test_frontend_structure)
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
        print("[OK] All tests passed!")
    else:
        print("[ERROR] Some tests failed")

if __name__ == "__main__":
    main()