#!/usr/bin/env python3
"""
Test script for Next.js Web UI (B-11)
"""

import asyncio
import requests
import json
import time
from typing import Dict, Any

BASE_URL = "http://localhost:8000"


def test_api_endpoints():
    """Test API endpoints for Next.js Web UI"""
    print("Testing Next.js Web UI API endpoints...")

    # Test sessions endpoint
    try:
        response = requests.get(f"{BASE_URL}/web/api/sessions")
        print(f"GET /web/api/sessions: {response.status_code}")
        if response.status_code == 200:
            print(f"  Response: {json.dumps(response.json(), indent=2)}")
        else:
            print(f"  Error: {response.text}")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test create session
    try:
        response = requests.post(f"{BASE_URL}/web/api/sessions")
        print(f"POST /web/api/sessions: {response.status_code}")
        if response.status_code == 201:
            session_data = response.json()
            session_id = session_data.get("id")
            print(f"  Created session: {session_id}")

            # Test get messages for session
            response = requests.get(
                f"{BASE_URL}/web/api/sessions/{session_id}/messages"
            )
            print(
                f"GET /web/api/sessions/{session_id}/messages: {response.status_code}"
            )
            if response.status_code == 200:
                print(f"  Messages: {json.dumps(response.json(), indent=2)}")

            # Test send message
            message_data = {"content": "Hello, this is a test message"}
            response = requests.post(
                f"{BASE_URL}/web/api/sessions/{session_id}/messages", json=message_data
            )
            print(
                f"POST /web/api/sessions/{session_id}/messages: {response.status_code}"
            )
            if response.status_code == 201:
                print(f"  Response: {json.dumps(response.json(), indent=2)}")
        else:
            print(f"  Error: {response.text}")
    except Exception as e:
        print(f"  Exception: {e}")


def test_web_interface():
    """Test web interface endpoints"""
    print("\nTesting web interface endpoints...")

    # Test chat interface
    try:
        response = requests.get(f"{BASE_URL}/web/")
        print(f"GET /web/: {response.status_code}")
        if response.status_code == 200:
            print("  Chat interface loaded successfully")
        else:
            print(f"  Error: {response.text}")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test sessions sidebar
    try:
        response = requests.get(f"{BASE_URL}/web/sessions")
        print(f"GET /web/sessions: {response.status_code}")
        if response.status_code == 200:
            print("  Sessions sidebar loaded successfully")
        else:
            print(f"  Error: {response.text}")
    except Exception as e:
        print(f"  Exception: {e}")

    # Test settings panel
    try:
        response = requests.get(f"{BASE_URL}/web/settings")
        print(f"GET /web/settings: {response.status_code}")
        if response.status_code == 200:
            print("  Settings panel loaded successfully")
        else:
            print(f"  Error: {response.text}")
    except Exception as e:
        print(f"  Exception: {e}")


def test_websocket_connection():
    """Test WebSocket connection"""
    print("\nTesting WebSocket connection...")

    try:
        import websockets

        # Test WebSocket connection
        uri = "ws://localhost:8000/ws/test-session"

        async def test_websocket():
            try:
                async with websockets.connect(uri) as websocket:
                    print("  WebSocket connection successful")

                    # Send a test message
                    test_message = {
                        "type": "message",
                        "content": "Hello from test",
                        "session_id": "test-session",
                    }
                    await websocket.send(json.dumps(test_message))
                    print("  Test message sent")

                    # Wait for response
                    response = await asyncio.wait_for(websocket.recv(), timeout=5.0)
                    print(f"  Response received: {response}")

            except websockets.ConnectionClosed:
                print("  WebSocket connection closed")
            except Exception as e:
                print(f"  WebSocket error: {e}")

        # Run the test
        asyncio.run(test_websocket())

    except ImportError:
        print("  websockets library not available, skipping WebSocket test")
    except Exception as e:
        print(f"  Exception: {e}")


def main():
    """Main test function"""
    print("=== OryaAgent Next.js Web UI (B-11) Test ===")
    print(f"Base URL: {BASE_URL}")
    print()

    # Check if server is running
    try:
        response = requests.get(f"{BASE_URL}/health")
        if response.status_code == 200:
            print("[OK] OryaAgent server is running")
        else:
            print("[ERROR] OryaAgent server is not responding properly")
            return
    except Exception as e:
        print(f"[ERROR] Cannot connect to OryaAgent server: {e}")
        print("Please make sure the server is running on localhost:8000")
        return

    print()

    # Run tests
    test_api_endpoints()
    test_web_interface()
    test_websocket_connection()

    print("\n=== Test Complete ===")


if __name__ == "__main__":
    main()
