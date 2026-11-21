"""Simple test for WebSocket functionality."""

import pytest

from app.web.websocket_models import (
    MessageType,
    WebSocketMessage,
    create_assistant_message,
    create_user_message,
    parse_websocket_message,
    serialize_message,
)


def test_message_creation():
    """Test WebSocket message creation."""
    # Test user message creation
    user_msg = create_user_message("Hello", "session_123")
    assert user_msg.type == MessageType.USER
    assert user_msg.content == "Hello"
    assert user_msg.session_id == "session_123"

    # Test assistant message creation
    assistant_msg = create_assistant_message("Hi there!", "session_123")
    assert assistant_msg.type == MessageType.ASSISTANT
    assert assistant_msg.content == "Hi there!"
    assert assistant_msg.session_id == "session_123"


def test_message_serialization():
    """Test message serialization and deserialization."""
    # Create a message
    original_msg = create_user_message("Test message", "session_123")

    # Serialize to JSON
    json_str = serialize_message(original_msg)
    assert isinstance(json_str, str)

    # Deserialize from JSON
    parsed_msg = parse_websocket_message(json_str)
    assert parsed_msg.type == MessageType.USER
    assert parsed_msg.content == "Test message"
    assert parsed_msg.session_id == "session_123"


def test_message_validation():
    """Test message validation."""
    from app.web.websocket_models import validate_message

    # Valid message should pass validation
    valid_msg = create_user_message("Hello", "session_123")
    assert validate_message(valid_msg)

    # Invalid message (no content and not a special type) should fail
    invalid_msg = WebSocketMessage(type=MessageType.USER)
    assert not validate_message(invalid_msg)

    # Special type message without content should pass
    special_msg = WebSocketMessage(type=MessageType.CONNECTION)
    assert validate_message(special_msg)


def test_message_types():
    """Test all message types."""
    from app.web.websocket_models import (
        create_connection_message,
        create_error_message,
        create_status_message,
        create_stream_complete_message,
        create_stream_token_message,
        create_tool_call_message,
        create_tool_result_message,
    )

    # Test error message
    error_msg = create_error_message("Something went wrong", "session_123")
    assert error_msg.type == MessageType.ERROR
    assert error_msg.error_message == "Something went wrong"

    # Test tool call message
    tool_call_msg = create_tool_call_message(
        "read_file", {"path": "test.txt"}, "tool_call_123", "session_123"
    )
    assert tool_call_msg.type == MessageType.TOOL_CALL
    assert tool_call_msg.tool_name == "read_file"
    assert tool_call_msg.tool_call_id == "tool_call_123"

    # Test tool result message
    tool_result_msg = create_tool_result_message(
        "read_file", "tool_call_123", {"content": "File content"}, 1000, "session_123"
    )
    assert tool_result_msg.type == MessageType.TOOL_RESULT
    assert tool_result_msg.tool_name == "read_file"
    assert tool_result_msg.result == {"content": "File content"}

    # Test stream token message
    stream_token_msg = create_stream_token_message("Hello", 0, "session_123", 5)
    assert stream_token_msg.type == MessageType.STREAM_TOKEN
    assert stream_token_msg.content == "Hello"
    assert stream_token_msg.position == 0
    assert stream_token_msg.total_tokens == 5

    # Test stream complete message
    stream_complete_msg = create_stream_complete_message("session_123")
    assert stream_complete_msg.type == MessageType.STREAM_COMPLETE

    # Test connection message
    connection_msg = create_connection_message("conn_123", "connected")
    assert connection_msg.type == MessageType.CONNECTION
    assert connection_msg.connection_id == "conn_123"
    assert connection_msg.status_type == "connected"

    # Test status message
    status_msg = create_status_message("healthy", {"active_connections": 10})
    assert status_msg.type == MessageType.STATUS
    assert status_msg.status_type == "healthy"
    assert status_msg.details == {"active_connections": 10}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
