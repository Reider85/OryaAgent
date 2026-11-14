#!/usr/bin/env python3
"""
Simple verification script for B-20 Hooks UI implementation.
"""

import sys
from pathlib import Path

# Add the project root to the Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def verify_implementation():
    """Verify that all components are implemented correctly."""
    print("=== B-20 Hooks UI Implementation Verification ===\n")
    
    # Check templates
    templates_dir = project_root / "app" / "web" / "templates" / "hooks"
    base_template = project_root / "app" / "web" / "templates" / "base.html"
    
    print("1. Checking templates:")
    if templates_dir.exists():
        print("   [OK] Templates directory exists")
        templates = ["hooks.html", "execution-log.html", "detail.html", "statistics.html"]
        for template in templates:
            template_path = templates_dir / template
            if template_path.exists():
                print(f"   [OK] {template} exists")
            else:
                print(f"   [ERROR] {template} missing")
    else:
        print("   ✗ Templates directory missing")
    
    if base_template.exists():
        print("   [OK] Base template exists")
    else:
        print("   [ERROR] Base template missing")
    
    # Check hooks UI router
    print("\n2. Checking hooks UI router:")
    try:
        from app.web.hooks_ui import router
        print("   [OK] Hooks UI router imported successfully")
        
        routes = [route.path for route in router.routes]
        expected_routes = [
            "/ui/hooks/",
            "/ui/hooks/execution-log",
            "/ui/hooks/detail/{hook_name}",
            "/ui/hooks/statistics"
        ]
        
        for route in expected_routes:
            if route in routes:
                print(f"   [OK] Route {route} exists")
            else:
                print(f"   [ERROR] Route {route} missing")
                
    except Exception as e:
        print(f"   ✗ Error importing hooks UI router: {e}")
    
    # Check hooks API
    print("\n3. Checking hooks API:")
    try:
        from app.api.hooks import router
        print("   [OK] Hooks API router imported successfully")
        
        routes = [route.path for route in router.routes]
        expected_endpoints = [
            "/hooks/executed",
            "/hooks/registry", 
            "/hooks/statistics",
            "/hooks/csv"
        ]
        
        for endpoint in expected_endpoints:
            if endpoint in routes:
                print(f"   [OK] Endpoint {endpoint} exists")
            else:
                print(f"   [ERROR] Endpoint {endpoint} missing")
                
    except Exception as e:
        print(f"   ✗ Error importing hooks API router: {e}")
    
    print("\n=== Verification Complete ===")
    print("\nTo use the Hooks UI:")
    print("1. Ensure the application is running: uvicorn app.main:app --reload")
    print("2. Access the Hooks UI at: http://localhost:8000/ui/hooks/")
    print("3. Test the different views:")
    print("   - Main audit log: /ui/hooks/")
    print("   - Execution log: /ui/hooks/execution-log")
    print("   - Statistics: /ui/hooks/statistics")
    print("   - Hook details: /ui/hooks/detail/{hook_name}")

if __name__ == "__main__":
    verify_implementation()