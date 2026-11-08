#!/usr/bin/env python3
"""
Deployment script for Next.js Web UI (B-11)
This script sets up the complete Next.js Web UI implementation
"""

import os
import sys
import subprocess
import shutil
from pathlib import Path


def check_dependencies():
    """Check if all required dependencies are available"""
    print("[INFO] Checking dependencies...")

    # Check Python dependencies
    try:
        import fastapi
        import uvicorn

        print("[OK] Python dependencies available")
    except ImportError as e:
        print(f"[ERROR] Missing Python dependency: {e}")
        return False

    # Check Node.js (for frontend)
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[OK] Node.js available: {result.stdout.strip()}")
        else:
            print("[ERROR] Node.js not available")
            return False
    except FileNotFoundError:
        print("[ERROR] Node.js not found")
        return False

    # Check npm
    try:
        result = subprocess.run(["npm", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"[OK] npm available: {result.stdout.strip()}")
        else:
            print("[ERROR] npm not available")
            return False
    except FileNotFoundError:
        print("[ERROR] npm not found")
        return False

    return True


def install_frontend_dependencies():
    """Install frontend dependencies"""
    print("\n[INFO] Installing frontend dependencies...")

    frontend_path = Path(__file__).parent / "nextjs"

    if not frontend_path.exists():
        print("[ERROR] Frontend directory not found")
        return False

    os.chdir(frontend_path)

    try:
        # Install dependencies
        result = subprocess.run(["npm", "install"], capture_output=True, text=True)
        if result.returncode == 0:
            print("[OK] Frontend dependencies installed")
            return True
        else:
            print(f"[ERROR] Failed to install dependencies: {result.stderr}")
            return False
    except Exception as e:
        print(f"[ERROR] Error installing dependencies: {e}")
        return False


def run_frontend_dev():
    """Run frontend development server"""
    print("\n[INFO] Starting frontend development server...")

    frontend_path = Path(__file__).parent / "nextjs"

    if not frontend_path.exists():
        print("[ERROR] Frontend directory not found")
        return False

    os.chdir(frontend_path)

    try:
        # Start development server
        subprocess.Popen(["npm", "run", "dev"])
        print("[OK] Frontend development server started")
        print("[INFO] Frontend available at: http://localhost:3000")
        return True
    except Exception as e:
        print(f"[ERROR] Error starting frontend server: {e}")
        return False


def run_backend_dev():
    """Run backend development server"""
    print("\n[INFO] Starting backend development server...")

    # Go back to app directory
    os.chdir(Path(__file__).parent.parent)

    try:
        # Start development server
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--reload",
                "--port",
                "8000",
            ]
        )
        print("[OK] Backend development server started")
        print("[INFO] Backend available at: http://localhost:8000")
        return True
    except Exception as e:
        print(f"[ERROR] Error starting backend server: {e}")
        return False


def run_tests():
    """Run all tests"""
    print("\n[INFO] Running tests...")

    test_path = Path(__file__).parent / "test_comprehensive.py"

    if not test_path.exists():
        print("[ERROR] Test file not found")
        return False

    os.chdir(Path(__file__).parent)

    try:
        result = subprocess.run(
            [sys.executable, "test_comprehensive.py"], capture_output=True, text=True
        )
        if result.returncode == 0:
            print("[OK] All tests passed")
            return True
        else:
            print(f"[ERROR] Tests failed: {result.stderr}")
            return False
    except Exception as e:
        print(f"[ERROR] Error running tests: {e}")
        return False


def main():
    """Main deployment function"""
    print("=== Next.js Web UI (B-11) Deployment Script ===")
    print()

    # Check if we're in the right directory
    if not Path(__file__).parent.name == "web":
        print("[ERROR] This script must be run from the app/web directory")
        return False

    # Check dependencies
    if not check_dependencies():
        print("[ERROR] Dependency check failed")
        return False

    # Install frontend dependencies
    if not install_frontend_dependencies():
        print("[ERROR] Frontend dependency installation failed")
        return False

    # Run tests
    if not run_tests():
        print("[ERROR] Tests failed")
        return False

    print("\n[INFO] Starting servers...")
    print("[INFO] This will start both frontend and backend servers")
    print("[INFO] Press Ctrl+C to stop both servers")
    print()

    # Start both servers
    frontend_ok = run_frontend_dev()
    backend_ok = run_backend_dev()

    if frontend_ok and backend_ok:
        print("\n[OK] Deployment complete!")
        print("\n=== Access Points ===")
        print("Frontend: http://localhost:3000")
        print("Backend: http://localhost:8000")
        print("API Docs: http://localhost:8000/web/docs")
        print("\n=== Testing ===")
        print("Run tests: python app/web/test_comprehensive.py")
        print("Check routes: python app/web/test_simple.py")
        print("\n=== Features ===")
        print("✓ Real-time chat interface")
        print("✓ WebSocket streaming")
        print("✓ Session management")
        print("✓ Tool call visualization")
        print("✓ Soft limit handling")
        print("✓ Authentication integration")
        print("✓ Responsive design")
    else:
        print("[ERROR] Server startup failed")
        return False


if __name__ == "__main__":
    main()
