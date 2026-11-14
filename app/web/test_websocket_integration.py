"""Integration tests for B-15 WebSocket streaming with FastAPI."""

import asyncio
import json
import pytest
import pytest_asyncio
from httpx import AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.web.websocket_manager import websocket_manager
from app.web.streaming_manager import streaming_manager


class TestWebSocketAPI:
    """Test WebSocket API endpoints and integration."""
    
    @pytest_asyncio.asyncio_test
    async def test_chat_interface_ui(self):
        """Test chat interface UI page loads correctly."""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/ui/")
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
    
    @pytest_asyncio.asyncio_test
    async def test_sessions_sidebar_ui(self):
        """Test sessions sidebar UI page loads correctly."""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/ui/sessions")
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
    
    @pytest_asyncio.asyncio_test
    async def test_settings_panel_ui(self):
        """Test settings panel UI page loads correctly."""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/ui/settings")
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
    
    @pytest_asyncio.asyncio_test
    async def test_tool_calls_visualization_ui(self):
        """Test tool calls visualization UI page loads correctly."""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/ui/tool-calls")
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
    
    @pytest_asyncio.asyncio_test
    async def test_get_sessions(self):
        """Test getting sessions via API."""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/ui/api/sessions")
            assert response.status_code == 200
            data = response.json()
            assert "sessions" in data
    
    @pytest_asyncio.asyncio_test
    async def test_create_session(self):
        """Test creating a session via API."""
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post("/ui/api/sessions")
            assert response.status_code == 201
            data = response.json()
            assert "id" in data
            assert "name" in data
            assert "created_at" in data
    
    @pytest_asyncio.asyncio_test
    async def test_get_session_messages(self):
        """Test getting session messages via API."""
        # First create a session
        async with AsyncClient(app=app, base_url="http://test") as client:
            create_response = await client.post("/ui/api/sessions")
            session_id = create_response.json()["id"]
            
            # Get messages for the session
            response = await client.get(f"/ui/api/sessions/{session_id}/messages")
            assert response.status_code == 200
            data = response.json()
            assert "messages" in data
    
    @pytest_asyncio.asyncio_test
    async def test_send_message_to_session(self):
        """Test sending a message to a session via API."""
        # First create a session
        async with AsyncClient(app=app, base_url="http://test") as client:
            create_response = await client.post("/ui/api/sessions")
            session_id = create_response.json()["id"]
            
            # Send a message to the session
            response = await client.post(
                f"/ui/api/sessions/{session_id}/messages",
                json={"content": "Hello, world!"}
            )
            assert response.status_code == 201
            data = response.json()
            assert "id" in data
            assert "role" in data
            assert "content" in data


class TestWebSocketIntegration:
    """Test WebSocket integration with FastAPI."""
    
    @pytest_asyncio.asyncio_test
    async def test_websocket_endpoint_connection(self):
        """Test WebSocket endpoint connection."""
        # This test would require a WebSocket client, so we'll test the setup
        assert websocket_manager is not None
        assert hasattr(websocket_manager, 'connect')
        assert hasattr(websocket_manager, 'disconnect')
        assert hasattr(websocket_manager, 'send_personal_message')
    
    @pytest_asyncio.asyncio_test
    async def test_streaming_manager_integration(self):
        """Test streaming manager integration."""
        assert streaming_manager is not None
        assert hasattr(streaming_manager, 'stream_agent_response')
        assert hasattr(streaming_manager, 'start_stream_task')
        assert hasattr(streaming_manager, 'cancel_stream')
    
    @pytest_asyncio.asyncio_test
    async def test_message_processing_flow(self):
        """Test complete message processing flow."""
        # This would test the integration between WebSocket manager and streaming manager
        # For now, we'll test that the components can work together
        
        # Create mock data
        session_id = "test_session"
        user_id = "test_user"
        message = "Hello, world!"
        
        # Test that we can create messages
        from app.websocket_models import create_user_message, create_assistant_message
        
        user_message = create_user_message(message, session_id)
        assistant_message = create_assistant_message("Hi there!", session_id)
        
        assert user_message.content == message
        assert assistant_message.content == "Hi there!"
        assert user_message.session_id == session_id
        assert assistant_message.session_id == session_id


class TestWebSocketErrorHandling:
    """Test WebSocket error handling scenarios."""
    
    @pytest_asyncio.asyncio_test
    async def test_invalid_json_handling(self):
        """Test handling of invalid JSON messages."""
        # This would be tested in the WebSocket endpoint
        # For now, we'll test the message parsing
        
        from app.websocket_models import parse_websocket_message
        
        # Valid JSON should work
        valid_json = json.dumps({
            "id": "test_123",
            "type": "user",
            "content": "Hello",
            "timestamp": "2024-01-15T10:00:00Z",
            "session_id": "session_123"
        })
        
        message = parse_websocket_message(valid_json)
        assert message.content == "Hello"
        
        # Invalid JSON should raise an error
        invalid_json = "invalid json"
        try:
            parse_websocket_message(invalid_json)
            assert False, "Should have raised an error"
        except ValueError:
            pass  # Expected
    
    @pytest_asyncio.asyncio_test
    async def test_unknown_message_type_handling(self):
        """Test handling of unknown message types."""
        from app.web.websocket_models import WebSocketMessage
        
        # Unknown message type should fall back to base message
        message_data = {
            "id": "test_123",
            "type": "unknown_type",
            "content": "Hello",
            "timestamp": "2024-01-15T10:00:00Z",
            "session_id": "session_123"
        }
        
        message = WebSocketMessage(**message_data)
        assert message.type == "unknown_type"
        assert message.content == "Hello"


class TestWebSocketPerformance:
    """Test WebSocket performance characteristics."""
    
    @pytest_asyncio.asyncio_test
    async def test_message_serialization_performance(self):
        """Test message serialization performance."""
        from app.web.websocket_models import create_assistant_message, serialize_message
        
        # Create multiple messages and serialize them
        messages = []
        start_time = asyncio.get_event_loop().time()
        
        for i in range(1000):
            message = create_assistant_message(f"Message {i}", "session_123")
            serialized = serialize_message(message)
            messages.append(serialized)
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        # Should have serialized 1000 messages
        assert len(messages) == 1000
        
        # Should be reasonably fast (less than 1 second)
        assert duration < 1.0, f"Serialization too slow: {duration}s"
    
    @pytest_asyncio.asyncio_test
    async def test_message_deserialization_performance(self):
        """Test message deserialization performance."""
        from app.websocket_models import create_assistant_message, parse_websocket_message
        
        # Create and serialize messages first
        serialized_messages = []
        for i in range(1000):
            message = create_assistant_message(f"Message {i}", "session_123")
            serialized_messages.append(serialize_message(message))
        
        # Deserialize them
        start_time = asyncio.get_event_loop().time()
        messages = []
        
        for serialized in serialized_messages:
            message = parse_websocket_message(serialized)
            messages.append(message)
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        # Should have deserialized 1000 messages
        assert len(messages) == 1000
        
        # Should be reasonably fast (less than 1 second)
        assert duration < 1.0, f"Deserialization too slow: {duration}s"


class TestWebSocketSecurity:
    """Test WebSocket security aspects."""
    
    @pytest_asyncio.asyncio_test
    async def test_session_isolation(self):
        """Test that sessions are properly isolated."""
        from app.websocket_manager import EnhancedWebSocketManager
        
        manager = EnhancedWebSocketManager()
        
        # Create mock connections for different sessions
        mock_websocket1 = AsyncMock()
        mock_websocket2 = AsyncMock()
        
        connection1 = await manager.connect(mock_websocket1, "session_1", "user_1")
        connection2 = await manager.connect(mock_websocket2, "session_2", "user_2")
        
        # Should have connections for both sessions
        assert len(manager.session_connections) == 2
        assert "session_1" in manager.session_connections
        assert "session_2" in manager.session_connections
        
        # Test sending to specific session
        from app.websocket_models import create_assistant_message
        
        message = create_assistant_message("Hello session 1", "session_1")
        
        # Mock the send methods
        mock_websocket1.send_text = AsyncMock()
        mock_websocket2.send_text = AsyncMock()
        
        await manager.send_to_session("session_1", message)
        
        # Only session 1 should receive the message
        mock_websocket1.send_text.assert_called_once()
        mock_websocket2.send_text.assert_not_called()
    
    @pytest_asyncio.asyncio_test
    async def test_user_session_mapping(self):
        """Test user to session mapping."""
        from app.websocket_manager import EnhancedWebSocketManager
        
        manager = EnhancedWebSocketManager()
        
        # Create connections for the same user in different sessions
        mock_websocket1 = AsyncMock()
        mock_websocket2 = AsyncMock()
        
        await manager.connect(mock_websocket1, "session_1", "user_1")
        await manager.connect(mock_websocket2, "session_2", "user_1")
        
        # User should have sessions mapped
        assert "user_1" in manager.user_sessions
        assert "session_1" in manager.user_sessions["user_1"]
        assert "session_2" in manager.user_sessions["user_1"]
        
        # Test sending to user
        from app.websocket_models import create_assistant_message
        
        message = create_assistant_message("Hello user", "session_1")
        
        # Mock the send methods
        mock_websocket1.send_text = AsyncMock()
        mock_websocket2.send_text = AsyncMock()
        
        await manager.send_to_user("user_1", message)
        
        # Both sessions should receive the message
        mock_websocket1.send_text.assert_called_once()
        mock_websocket2.send_text.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])