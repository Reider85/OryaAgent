"""WebSocket message types and API contracts for B-15 streaming."""

import json
import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MessageType(StrEnum):
    """WebSocket message types."""

    USER = "user"
    ASSISTANT = "assistant"
    ERROR = "error"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    STREAM_TOKEN = "stream_token"
    STREAM_COMPLETE = "stream_complete"
    CONNECTION = "connection"
    STATUS = "status"


class WebSocketMessage(BaseModel):
    """Base WebSocket message model."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: MessageType
    content: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    session_id: str | None = None
    role: str | None = None
    request_id: str | None = None
    position: int | None = None
    total_tokens: int | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    tool_call_id: str | None = None
    result: Any | None = None
    status: str | None = None
    start_time: str | None = None
    end_time: str | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    connection_id: str | None = None
    message: str | None = None
    status_type: str | None = None
    details: dict[str, Any] | None = None

    def to_json(self) -> str:
        """Convert message to JSON string."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "WebSocketMessage":
        """Create message from JSON string."""
        data = json.loads(json_str)
        return cls(**data)


class UserMessage(WebSocketMessage):
    """User message model."""

    type: MessageType = MessageType.USER
    content: str
    role: str = "user"

    @classmethod
    def create(cls, content: str, session_id: str) -> "UserMessage":
        """Create a user message."""
        return cls(content=content, session_id=session_id)


class AssistantMessage(WebSocketMessage):
    """Assistant message model."""

    type: MessageType = MessageType.ASSISTANT
    content: str
    role: str = "assistant"

    @classmethod
    def create(cls, content: str, session_id: str) -> "AssistantMessage":
        """Create an assistant message."""
        return cls(content=content, session_id=session_id)


class ErrorMessage(WebSocketMessage):
    """Error message model."""

    type: MessageType = MessageType.ERROR
    error_message: str

    @classmethod
    def create(cls, error_message: str, session_id: str = None) -> "ErrorMessage":
        """Create an error message."""
        return cls(error_message=error_message, session_id=session_id)


class ToolCallMessage(WebSocketMessage):
    """Tool call message model."""

    type: MessageType = MessageType.TOOL_CALL
    tool_name: str
    tool_args: dict[str, Any]
    tool_call_id: str
    start_time: str

    @classmethod
    def create(
        cls,
        tool_name: str,
        tool_args: dict[str, Any],
        tool_call_id: str,
        session_id: str,
    ) -> "ToolCallMessage":
        """Create a tool call message."""
        return cls(
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
            start_time=datetime.utcnow().isoformat(),
            session_id=session_id,
        )


class ToolResultMessage(WebSocketMessage):
    """Tool result message model."""

    type: MessageType = MessageType.TOOL_RESULT
    tool_name: str
    tool_call_id: str
    result: Any
    duration_ms: int
    end_time: str

    @classmethod
    def create(
        cls,
        tool_name: str,
        tool_call_id: str,
        result: Any,
        duration_ms: int,
        session_id: str,
    ) -> "ToolResultMessage":
        """Create a tool result message."""
        return cls(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            result=result,
            duration_ms=duration_ms,
            end_time=datetime.utcnow().isoformat(),
            session_id=session_id,
        )


class StreamTokenMessage(WebSocketMessage):
    """Stream token message model."""

    type: MessageType = MessageType.STREAM_TOKEN
    position: int
    total_tokens: int | None = None

    @classmethod
    def create(
        cls, token: str, position: int, session_id: str, total_tokens: int = None
    ) -> "StreamTokenMessage":
        """Create a stream token message."""
        return cls(
            content=token,
            position=position,
            total_tokens=total_tokens,
            session_id=session_id,
        )


class StreamCompleteMessage(WebSocketMessage):
    """Stream complete message model."""

    type: MessageType = MessageType.STREAM_COMPLETE

    @classmethod
    def create(cls, session_id: str) -> "StreamCompleteMessage":
        """Create a stream complete message."""
        return cls(session_id=session_id)


class ConnectionMessage(WebSocketMessage):
    """Connection status message model."""

    type: MessageType = MessageType.CONNECTION
    connection_id: str
    status_type: str  # "connected", "disconnected", "reconnecting"

    @classmethod
    def create(cls, connection_id: str, status_type: str) -> "ConnectionMessage":
        """Create a connection message."""
        return cls(connection_id=connection_id, status_type=status_type)


class StatusMessage(WebSocketMessage):
    """Status message model."""

    type: MessageType = MessageType.STATUS
    status_type: str
    details: dict[str, Any] | None = None

    @classmethod
    def create(
        cls, status_type: str, details: dict[str, Any] = None
    ) -> "StatusMessage":
        """Create a status message."""
        return cls(status_type=status_type, details=details)


# Message factory functions
def create_user_message(content: str, session_id: str) -> UserMessage:
    """Create a user message."""
    return UserMessage.create(content, session_id)


def create_assistant_message(content: str, session_id: str) -> AssistantMessage:
    """Create an assistant message."""
    return AssistantMessage.create(content, session_id)


def create_error_message(error_message: str, session_id: str = None) -> ErrorMessage:
    """Create an error message."""
    return ErrorMessage.create(error_message, session_id)


def create_tool_call_message(
    tool_name: str, tool_args: dict[str, Any], tool_call_id: str, session_id: str
) -> ToolCallMessage:
    """Create a tool call message."""
    return ToolCallMessage.create(tool_name, tool_args, tool_call_id, session_id)


def create_tool_result_message(
    tool_name: str, tool_call_id: str, result: Any, duration_ms: int, session_id: str
) -> ToolResultMessage:
    """Create a tool result message."""
    return ToolResultMessage.create(
        tool_name, tool_call_id, result, duration_ms, session_id
    )


def create_stream_token_message(
    token: str, position: int, session_id: str, total_tokens: int = None
) -> StreamTokenMessage:
    """Create a stream token message."""
    return StreamTokenMessage.create(token, position, session_id, total_tokens)


def create_stream_complete_message(session_id: str) -> StreamCompleteMessage:
    """Create a stream complete message."""
    return StreamCompleteMessage.create(session_id)


def create_connection_message(
    connection_id: str, status_type: str
) -> ConnectionMessage:
    """Create a connection message."""
    return ConnectionMessage.create(connection_id, status_type)


def create_status_message(
    status_type: str, details: dict[str, Any] = None
) -> StatusMessage:
    """Create a status message."""
    return StatusMessage.create(status_type, details)


# Serialization/deserialization functions
def serialize_message(message: WebSocketMessage) -> str:
    """Serialize a WebSocket message to JSON string."""
    return message.to_json()


def parse_websocket_message(json_str: str) -> WebSocketMessage:
    """Parse a WebSocket message from JSON string."""
    try:
        data = json.loads(json_str)
        message_type = data.get("type")

        # Create specific message type based on type field
        if message_type == MessageType.USER:
            return UserMessage(**data)
        elif message_type == MessageType.ASSISTANT:
            return AssistantMessage(**data)
        elif message_type == MessageType.ERROR:
            return ErrorMessage(**data)
        elif message_type == MessageType.TOOL_CALL:
            return ToolCallMessage(**data)
        elif message_type == MessageType.TOOL_RESULT:
            return ToolResultMessage(**data)
        elif message_type == MessageType.STREAM_TOKEN:
            return StreamTokenMessage(**data)
        elif message_type == MessageType.STREAM_COMPLETE:
            return StreamCompleteMessage(**data)
        elif message_type == MessageType.CONNECTION:
            return ConnectionMessage(**data)
        elif message_type == MessageType.STATUS:
            return StatusMessage(**data)
        else:
            # Fall back to base WebSocketMessage for unknown types
            return WebSocketMessage(**data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON message: {e}")
    except Exception as e:
        raise ValueError(f"Failed to parse message: {e}")


# Message validation
def validate_message(message: WebSocketMessage) -> bool:
    """Validate a WebSocket message."""
    if not message.content and message.type not in [
        MessageType.CONNECTION,
        MessageType.STREAM_COMPLETE,
    ]:
        return False

    if message.session_id is None and message.type not in [MessageType.STATUS]:
        return False

    return True
