"""Comprehensive tests for B-15 WebSocket streaming functionality."""

import asyncio
import json
import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime
import websockets

from app.web.websocket_manager import websocket_manager, EnhancedWebSocketManager
from app.web.streaming_manager import streaming_manager, StreamingManager
from app.websocket_models import (
    WebSocketMessage,
    MessageType,
    parse_websocket_message,
    create_user_message,
    create_assistant_message,
    create_error_message,
    create_tool_call_message,
    create_stream_token_message,
    create_stream_complete_message,
)


class TestWebSocketModels:
    """Test WebSocket message models and parsing."""
    
    def test_parse_websocket_message(self):
        """Test parsing WebSocket messages from JSON."""
        message_data = {
            "id": "test_123",
            "type": "user",
            "content": "Hello, world!",
            "timestamp": "2024-01-15T10:00:00Z",
            "session_id": "session_123",
        }
        
        message = parse_websocket_message(json.dumps(message_data))
        
        assert message.id == "test_123"
        assert message.type == MessageType.USER
        assert message.content == "Hello, world!"
        assert message.session_id == "session_123"
    
    def test_create_user_message(self):
        """Test creating user messages."""
        message = create_user_message("Hello", "session_123")
        
        assert message.type == MessageType.USER
        assert message.content == "Hello"
        assert message.session_id == "session_123"
        assert message.role == "user"
        assert "id" in message
        assert "timestamp" in message
    
    def test_create_assistant_message(self):
        """Test creating assistant messages."""
        message = create_assistant_message("Hi there!", "session_123", position=5, total_tokens=10)
        
        assert message.type == MessageType.ASSISTANT
        assert message.content == "Hi there!"
        assert message.session_id == "session_123"
        assert message.position == 5
        assert message.total_tokens == 10
        assert message.role == "assistant"
    
    def test_create_error_message(self):
        """Test creating error messages."""
        message = create_error_message("Something went wrong", "session_123", "ERROR_001")
        
        assert message.type == MessageType.ERROR
        assert message.content == "Something went wrong"
        assert message.session_id == "session_123"
        assert message.error_code == "ERROR_001"
    
    def test_create_stream_token_message(self):
        """Test creating stream token messages."""
        message = create_stream_token_message("Hello", 1, "session_123", "stream_123", 5)
        
        assert message.type == MessageType.STREAM_TOKEN
        assert message.content == "Hello"
        assert message.position == 1
        assert message.session_id == "session_123"
        assert message.request_id == "stream_123"
        assert message.total_tokens == 5


class TestEnhancedWebSocketManager:
    """Test enhanced WebSocket manager functionality."""
    
    @pytest.fixture
    def mock_websocket(self):
        """Create a mock WebSocket connection."""
        websocket = AsyncMock()
        websocket.accept = AsyncMock()
        websocket.send_text = AsyncMock()
        websocket.close = AsyncMock()
        websocket.receive_text = AsyncMock()
        return websocket
    
    @pytest.fixture
    def mock_connection(self, mock_websocket):
        """Create a mock connection object."""
        from app.websocket_manager import WebSocketConnection
        
        connection = WebSocketConnection(
            websocket=mock_websocket,
            session_id="test_session",
            user_id="test_user"
        )
        return connection
    
    @pytest_asyncio.asyncio_test
    async def test_connect(self, mock_websocket):
        """Test WebSocket connection."""
        manager = EnhancedWebSocketManager()
        
        connection = await manager.connect(mock_websocket, "test_session", "test_user")
        
        assert connection.session_id == "test_session"
        assert connection.user_id == "test_user"
        assert connection.is_active == True
        assert connection.connection_id is not None
        assert manager.total_connections == 1
    
    @pytest_asyncio.asyncio_test
    async def test_send_personal_message(self, mock_connection):
        """Test sending personal messages."""
        manager = EnhancedWebSocketManager()
        
        # Mock the send method
        mock_connection.websocket.send_text = AsyncMock()
        
        message = create_assistant_message("Hello", "test_session")
        await manager.send_personal_message(message, mock_connection)
        
        mock_connection.websocket.send_text.assert_called_once()
        call_args = mock_connection.websocket.send_text.call_args[0][0]
        parsed_message = json.loads(call_args)
        assert parsed_message["type"] == "assistant"
        assert parsed_message["content"] == "Hello"
    
    @pytest_asyncio.asyncio_test
    async def test_send_to_session(self, mock_websocket):
        """Test broadcasting to session."""
        manager = EnhancedWebSocketManager()
        
        # Create mock connections
        connection1 = AsyncMock()
        connection1.websocket = mock_websocket
        connection1.is_active = True
        connection1.send_message = AsyncMock()
        
        connection2 = AsyncMock()
        connection2.websocket = mock_websocket
        connection2.is_active = True
        connection2.send_message = AsyncMock()
        
        manager.session_connections["test_session"] = [connection1, connection2]
        
        message = create_assistant_message("Hello everyone", "test_session")
        await manager.send_to_session("test_session", message)
        
        # Both connections should receive the message
        connection1.send_message.assert_called_once()
        connection2.send_message.assert_called_once()
    
    @pytest_asyncio.asyncio_test
    async def test_handle_message(self, mock_connection):
        """Test handling incoming messages."""
        manager = EnhancedWebSocketManager()
        message_received = False
        
        def message_handler(connection, message):
            nonlocal message_received
            message_received = True
            assert connection == mock_connection
            assert message.type == MessageType.USER
        
        manager.set_message_handler(message_handler)
        
        message_data = json.dumps(create_user_message("Hello", "test_session").model_dump())
        await manager.handle_message(mock_connection, message_data)
        
        assert message_received == True
    
    @pytest_asyncio.asyncio_test
    async def test_connection_cleanup(self, mock_websocket):
        """Test cleanup of inactive connections."""
        manager = EnhancedWebSocketManager()
        
        # Create mock connections
        connection1 = AsyncMock()
        connection1.websocket = mock_websocket
        connection1.is_active = True
        
        connection2 = AsyncMock()
        connection2.websocket = mock_websocket
        connection2.is_active = False  # Inactive
        
        manager.session_connections["test_session"] = [connection1, connection2]
        
        manager.cleanup_inactive_connections()
        
        # Only active connection should remain
        assert len(manager.session_connections["test_session"]) == 1
        assert manager.session_connections["test_session"][0] == connection1
    
    @pytest_asyncio.asyncio_test
    async def test_get_statistics(self):
        """Test getting connection statistics."""
        manager = EnhancedWebSocketManager()
        
        # Add some test data
        manager.total_connections = 5
        manager.total_messages_sent = 100
        manager.total_messages_received = 95
        manager.streams_completed = 3
        manager.streams_failed = 1
        
        stats = manager.get_connection_statistics()
        
        assert stats["total_connections"] == 5
        assert stats["total_messages_sent"] == 100
        assert stats["total_messages_received"] == 95
        assert stats["streams_completed"] == 3
        assert stats["streams_failed"] == 1


class TestStreamingManager:
    """Test streaming manager functionality."""
    
    @pytest.fixture
    def mock_graph(self):
        """Create a mock graph."""
        graph = AsyncMock()
        graph.astream = AsyncMock()
        return graph
    
    @pytest.fixture
    def mock_tools(self):
        """Create mock tools."""
        tools = [AsyncMock(), AsyncMock()]
        return tools
    
    @pytest_asyncio.asyncio_test
    async def test_stream_agent_response(self, mock_graph, mock_tools):
        """Test streaming agent response."""
        manager = StreamingManager()
        
        # Mock the graph building
        with patch('app.streaming_manager.build_graph') as build_graph_mock:
            build_graph_mock.return_value = mock_graph
            
            # Mock the streaming response
            async def mock_stream():
                messages = [
                    {"messages": [{"content": "Hello", "role": "assistant"}]},
                    {"messages": [{"content": "Hello world", "role": "assistant"}]},
                ]
                for chunk in messages:
                    yield chunk
            
            mock_graph.astream.return_value = mock_stream()
            
            # Mock the tools
            with patch('app.streaming_manager.get_tools') as get_tools_mock:
                get_tools_mock.return_value = mock_tools
                
                # Test streaming
                messages = []
                async for message in manager.stream_agent_response(
                    session_id="test_session",
                    message="Hello",
                    user_id="test_user",
                    model="haiku"
                ):
                    messages.append(message)
                
                # Should have received messages
                assert len(messages) > 0
                assert any(msg.type == MessageType.ASSISTANT for msg in messages)
    
    @pytest_asyncio.asyncio_test
    async def test_execute_tool(self, mock_tools):
        """Test tool execution."""
        manager = StreamingManager()
        
        # Mock the tools
        with patch('app.streaming_manager.get_tools') as get_tools_mock:
            get_tools_mock.return_value = mock_tools
            
            # Mock tool execution
            mock_tools[0].ainvoke = AsyncMock(return_value="Tool result")
            
            result = await manager._execute_tool("test_tool", {"arg1": "value1"}, "test_session")
            
            assert result == "Tool result"
            mock_tools[0].ainvoke.assert_called_once_with({"arg1": "value1"})
    
    @pytest_asyncio.asyncio_test
    async def test_split_into_tokens(self):
        """Test token splitting."""
        manager = StreamingManager()
        
        text = "Hello world! How are you?"
        tokens = manager._split_into_tokens(text)
        
        assert isinstance(tokens, list)
        assert len(tokens) > 0
        assert "Hello" in tokens[0]
    
    @pytest_asyncio.asyncio_test
    async def test_start_stream_task(self, mock_graph, mock_tools):
        """Test starting a streaming task."""
        manager = StreamingManager()
        
        with patch('app.streaming_manager.build_graph') as build_graph_mock:
            build_graph_mock.return_value = mock_graph
            
            with patch('app.streaming_manager.get_tools') as get_tools_mock:
                get_tools_mock.return_value = mock_tools
                
                # Mock the streaming response
                async def mock_stream():
                    yield create_assistant_message("Hello", "test_session")
                
                mock_graph.astream.return_value = mock_stream()
                
                stream_id = await manager.start_stream_task(
                    session_id="test_session",
                    message="Hello",
                    user_id="test_user",
                    model="haiku"
                )
                
                assert stream_id is not None
                assert stream_id in manager.active_streams


class TestWebSocketIntegration:
    """Integration tests for WebSocket functionality."""
    
    @pytest_asyncio.asyncio_test
    async def test_websocket_lifecycle(self):
        """Test complete WebSocket lifecycle."""
        manager = EnhancedWebSocketManager()
        
        # Create mock WebSocket
        mock_websocket = AsyncMock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_text = AsyncMock()
        mock_websocket.close = AsyncMock()
        mock_websocket.receive_text = AsyncMock()
        
        # Test connection
        connection = await manager.connect(mock_websocket, "test_session", "test_user")
        assert connection.is_active == True
        
        # Test message sending
        message = create_assistant_message("Hello", "test_session")
        await manager.send_personal_message(message, connection)
        
        # Test disconnection
        manager.disconnect(connection)
        assert connection.is_active == False
    
    @pytest_asyncio.asyncio_test
    async def test_error_handling(self):
        """Test error handling in WebSocket operations."""
        manager = EnhancedWebSocketManager()
        
        # Create mock WebSocket that will raise an error
        mock_websocket = AsyncMock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_text = AsyncMock(side_effect=Exception("Connection error"))
        mock_websocket.close = AsyncMock()
        mock_websocket.receive_text = AsyncMock()
        
        # Test connection with error handling
        connection = await manager.connect(mock_websocket, "test_session", "test_user")
        
        # Test sending message that will fail
        message = create_assistant_message("Hello", "test_session")
        await manager.send_personal_message(message, connection)
        
        # Connection should be marked as inactive after error
        assert connection.is_active == False
    
    @pytest_asyncio.asyncio_test
    async def test_concurrent_connections(self):
        """Test handling multiple concurrent connections."""
        manager = EnhancedWebSocketManager()
        
        # Create multiple mock WebSockets
        websockets = [AsyncMock() for _ in range(3)]
        for ws in websockets:
            ws.accept = AsyncMock()
            ws.send_text = AsyncMock()
            ws.close = AsyncMock()
            ws.receive_text = AsyncMock()
        
        # Connect all WebSockets
        connections = []
        for ws in websockets:
            connection = await manager.connect(ws, "test_session", "test_user")
            connections.append(connection)
        
        # Should have 3 connections
        assert len(manager.session_connections["test_session"]) == 3
        assert manager.total_connections == 3
        
        # Broadcast message to all connections
        message = create_assistant_message("Hello everyone", "test_session")
        await manager.send_to_session("test_session", message)
        
        # All connections should receive the message
        for ws in websockets:
            ws.send_text.assert_called()
        
        # Disconnect all connections
        for connection in connections:
            manager.disconnect(connection)
        
        # Should have no connections
        assert len(manager.session_connections["test_session"]) == 0


class TestWebSocketPerformance:
    """Performance tests for WebSocket functionality."""
    
    @pytest_asyncio.asyncio_test
    async def test_message_throughput(self):
        """Test message throughput performance."""
        manager = EnhancedWebSocketManager()
        
        # Create mock WebSocket
        mock_websocket = AsyncMock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_text = AsyncMock()
        mock_websocket.close = AsyncMock()
        mock_websocket.receive_text = AsyncMock()
        
        # Connect
        connection = await manager.connect(mock_websocket, "test_session", "test_user")
        
        # Send multiple messages
        start_time = asyncio.get_event_loop().time()
        message_count = 100
        
        for i in range(message_count):
            message = create_stream_token_message(f"Token {i}", i, "test_session", "stream_123")
            await manager.send_personal_message(message, connection)
        
        end_time = asyncio.get_event_loop().time()
        duration = end_time - start_time
        
        # Should have sent all messages
        assert mock_websocket.send_text.call_count == message_count
        
        # Performance should be reasonable (less than 1 second for 100 messages)
        assert duration < 1.0, f"Message throughput too slow: {duration}s for {message_count} messages"
    
    @pytest_asyncio.asyncio_test
    async def test_concurrent_message_handling(self):
        """Test handling concurrent messages."""
        manager = EnhancedWebSocketManager()
        
        # Create mock WebSocket
        mock_websocket = AsyncMock()
        mock_websocket.accept = AsyncMock()
        mock_websocket.send_text = AsyncMock()
        mock_websocket.close = AsyncMock()
        mock_websocket.receive_text = AsyncMock()
        
        # Connect
        connection = await manager.connect(mock_websocket, "test_session", "test_user")
        
        # Send concurrent messages
        async def send_message(message_id):
            message = create_stream_token_message(f"Message {message_id}", message_id, "test_session", "stream_123")
            await manager.send_personal_message(message, connection)
        
        tasks = [send_message(i) for i in range(50)]
        await asyncio.gather(*tasks)
        
        # Should have sent all messages
        assert mock_websocket.send_text.call_count == 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])