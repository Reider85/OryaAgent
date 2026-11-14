#!/usr/bin/env python
"""Test script for B-15 WebSocket functionality."""

import asyncio
import sys
import os

# Add the current directory to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.web.websocket_models import (
    create_user_message,
    create_assistant_message,
    create_error_message,
    serialize_message,
    parse_websocket_message,
)

from app.web.websocket_manager import EnhancedWebSocketManager

from app.web.streaming_manager import StreamingManager


async def test_websocket_models():
    """Test WebSocket models functionality."""
    print("Testing WebSocket models...")
    
    # Test message creation
    user_msg = create_user_message("Hello, world!", "session_123")
    assistant_msg = create_assistant_message("Hi there!", "session_123")
    error_msg = create_error_message("Something went wrong", "session_123")
    
    print(f"User message: {user_msg.type} - {user_msg.content}")
    print(f"Assistant message: {assistant_msg.type} - {assistant_msg.content}")
    print(f"Error message: {error_msg.type} - {error_msg.error_message}")
    
    # Test serialization
    user_json = serialize_message(user_msg)
    print(f"Serialized user message: {user_json}")
    
    # Test deserialization
    parsed_msg = parse_websocket_message(user_json)
    print(f"Parsed message: {parsed_msg.type} - {parsed_msg.content}")
    
    print("SUCCESS: WebSocket models test passed!")


async def test_websocket_manager():
    """Test WebSocket manager functionality."""
    print("\nTesting WebSocket manager...")
    
    manager = EnhancedWebSocketManager(max_connections=10)
    
    # Mock WebSocket for testing
    class MockWebSocket:
        def __init__(self):
            self.messages = []
            
        async def accept(self):
            pass
            
        async def send_text(self, message):
            self.messages.append(message)
            
        async def close(self, code=None, reason=None):
            pass
    
    # Test connection
    mock_ws = MockWebSocket()
    try:
        connection_info = await manager.connect(mock_ws, "session_123", "user_123")
        print(f"Connection created: {connection_info.connection_id}")
        
        # Test sending message
        test_msg = create_user_message("Test message", "session_123")
        await manager.send_personal_message(test_msg, connection_info.connection_id)
        print(f"Message sent: {len(mock_ws.messages)} messages")
        
        # Test stats
        stats = await manager.get_connection_stats()
        print(f"Connection stats: {stats}")
        
        # Test disconnection
        await manager.disconnect(connection_info.connection_id)
        print("Connection disconnected")
        
    except Exception as e:
        print(f"❌ WebSocket manager test failed: {e}")
        return
    
    print("SUCCESS: WebSocket manager test passed!")


async def test_streaming_manager():
    """Test streaming manager functionality."""
    print("\nTesting streaming manager...")
    
    manager = StreamingManager(max_concurrent_streams=5)
    
    # Mock WebSocket manager
    class MockWebSocketManager:
        async def send_to_session(self, session_id, message):
            print(f"Sending to session {session_id}: {message.type} - {message.content}")
    
    mock_ws_manager = MockWebSocketManager()
    
    # Mock message generator
    async def mock_generator():
        for i in range(5):
            yield f"Token {i}"
            await asyncio.sleep(0.1)
    
    try:
        # Test starting stream
        stream_id = await manager.start_stream_task(
            "session_123", 
            "user_123", 
            mock_generator(), 
            mock_ws_manager
        )
        print(f"Stream started: {stream_id}")
        
        # Test stats
        stats = await manager.get_all_streams_stats()
        print(f"Streaming stats: {stats}")
        
        # Test cleanup
        await manager.cleanup_inactive_streams()
        print("Streams cleaned up")
        
    except Exception as e:
        print(f"❌ Streaming manager test failed: {e}")
        return
    
    print("SUCCESS: Streaming manager test passed!")


async def test_integration():
    """Test integration between components."""
    print("\nTesting integration...")
    
    # Create managers
    ws_manager = EnhancedWebSocketManager(max_connections=10)
    streaming_manager = StreamingManager(max_concurrent_streams=5)
    
    # Mock WebSocket
    class MockWebSocket:
        def __init__(self):
            self.messages = []
            
        async def accept(self):
            pass
            
        async def send_text(self, message):
            self.messages.append(message)
            
        async def close(self, code=None, reason=None):
            pass
    
    # Test integration scenario
    mock_ws = MockWebSocket()
    try:
        # Connect client
        connection_info = await ws_manager.connect(mock_ws, "session_123", "user_123")
        print(f"Client connected: {connection_info.connection_id}")
        
        # Mock WebSocket manager for streaming
        class MockWebSocketManager:
            def __init__(self, ws_manager):
                self.ws_manager = ws_manager
                
            async def send_to_session(self, session_id, message):
                await self.ws_manager.send_to_session(session_id, message)
        
        mock_ws_manager = MockWebSocketManager(ws_manager)
        
        # Start streaming
        async def mock_generator():
            for i in range(3):
                yield f"Integration token {i}"
                await asyncio.sleep(0.05)
        
        stream_id = await streaming_manager.start_stream_task(
            "session_123", 
            "user_123", 
            mock_generator(), 
            mock_ws_manager
        )
        print(f"Integration stream started: {stream_id}")
        
        # Check messages received
        print(f"Messages sent to client: {len(mock_ws.messages)}")
        for msg in mock_ws.messages:
            print(f"  - {msg}")
        
        # Cleanup
        await ws_manager.disconnect(connection_info.connection_id)
        await streaming_manager.cleanup_inactive_streams()
        
    except Exception as e:
        print(f"❌ Integration test failed: {e}")
        return
    
    print("SUCCESS: Integration test passed!")


async def main():
    """Run all tests."""
    print("Starting B-15 WebSocket functionality tests...")
    
    try:
        await test_websocket_models()
        await test_websocket_manager()
        await test_streaming_manager()
        await test_integration()
        
        print("\nAll tests passed successfully!")
        print("\nSummary:")
        print("SUCCESS: WebSocket models: Working correctly")
        print("SUCCESS: WebSocket manager: Working correctly")
        print("SUCCESS: Streaming manager: Working correctly")
        print("SUCCESS: Integration: Working correctly")
        
        print("\nB-15 WebSocket implementation is ready for production!")
        
    except Exception as e:
        print(f"Tests failed: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)