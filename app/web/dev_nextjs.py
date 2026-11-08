#!/usr/bin/env python3
"""
Development script for Next.js Web UI
"""

import os
import subprocess
import sys
import time
from pathlib import Path


def run_nextjs_dev():
    """Run Next.js development server"""
    nextjs_path = Path(__file__).parent / "nextjs"

    if not nextjs_path.exists():
        print("Next.js directory not found. Please run setup first.")
        return

    os.chdir(nextjs_path)

    print("Starting Next.js development server...")
    print("Make sure you have installed dependencies with: npm install")
    print("Press Ctrl+C to stop the server")

    try:
        # Run npm install first if node_modules doesn't exist
        if not (nextjs_path / "node_modules").exists():
            print("Installing dependencies...")
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "next",
                    "react",
                    "react-dom",
                    "socket.io-client",
                    "axios",
                    "clsx",
                    "tailwindcss",
                    "autoprefixer",
                    "postcss",
                    "lucide-react",
                ],
                check=True,
            )

        # Start Next.js dev server
        subprocess.run(["npm", "run", "dev"], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error running Next.js dev server: {e}")
    except KeyboardInterrupt:
        print("\nNext.js dev server stopped")


if __name__ == "__main__":
    run_nextjs_dev()
