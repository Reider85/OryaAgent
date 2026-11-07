"""WebSocket for streaming (B-15) - real-time token streaming.

Provides WebSocket endpoints for real-time streaming of agent responses.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from app.core.session import SessionManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui/api", tags=["nextjs-web-ui"])


class StreamingMessage(BaseModel):
    """Streaming message model."""
    type: str
    data: Any
    timestamp: str
    session_id: str
    turn_id: Optional[str] = None


class ConnectionManager:
    """Manager for WebSocket connections."""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}
        self.session_streams: Dict[str, asyncio.Queue] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept a WebSocket connection."""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
            self.session_streams[session_id] = asyncio.Queue()
        self.active_connections[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        """Disconnect a WebSocket connection."""
        if session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
                if session_id in self.session_streams:
                    del self.session_streams[session_id]

    async def send_message(self, message: StreamingMessage, session_id: str):
        """Send a message to all connections in a session."""
        if session_id in self.active_connections:
            message_json = message.model_dump_json()
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_text(message_json)
                except Exception as e:
                    logger.error(f"Failed to send message to WebSocket: {e}")

    async def stream_to_session(self, session_id: str, stream_data: List[Dict[str, Any]]):
        """Stream data to all connections in a session."""
        if session_id in self.session_streams:
            for data in stream_data:
                message = StreamingMessage(
                    type="stream",
                    data=data,
                    timestamp=datetime.utcnow().isoformat(),
                    session_id=session_id,
                )
                await self.session_streams[session_id].put(message)

    async def get_stream(self, session_id: str) -> asyncio.Queue:
        """Get the stream queue for a session."""
        if session_id not in self.session_streams:
            self.session_streams[session_id] = asyncio.Queue()
        return self.session_streams[session_id]


connection_manager = ConnectionManager()


class StreamingManager:
    """Manager for streaming agent responses."""

    def __init__(self):
        self.session_manager = SessionManager()

    async def start_stream(self, session_id: str, message: str) -> str:
        """Start a new stream for a session."""
        try:
            # Create a new turn for the stream
            turn_id = str(uuid.uuid4())
            
            # Initialize turn with user message
            turn_data = {
                "id": turn_id,
                "session_id": session_id,
                "turn_number": await self._get_next_turn_number(session_id),
                "messages": [
                    {
                        "role": "user",
                        "content": message,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                ],
                "tool_calls": [],
                "created_at": datetime.utcnow().isoformat(),
                "metadata": {
                    "streaming": True,
                    "stream_id": str(uuid.uuid4()),
                },
            }
            
            # Save turn
            await self.session_manager.create_turn(turn_data)
            
            # Send stream start message
            start_message = StreamingMessage(
                type="stream_start",
                data={
                    "turn_id": turn_id,
                    "message": message,
                    "stream_id": turn_data["metadata"]["stream_id"],
                },
                timestamp=datetime.utcnow().isoformat(),
                session_id=session_id,
                turn_id=turn_id,
            )
            await connection_manager.send_message(start_message, session_id)
            
            return turn_id

        except Exception as e:
            logger.error(f"Failed to start stream: {e}")
            raise ValueError(f"Failed to start stream: {str(e)}")

    async def stream_token(self, session_id: str, turn_id: str, token: str):
        """Stream a token to the session."""
        try:
            message = StreamingMessage(
                type="token",
                data={"token": token, "turn_id": turn_id},
                timestamp=datetime.utcnow().isoformat(),
                session_id=session_id,
                turn_id=turn_id,
            )
            await connection_manager.send_message(message, session_id)

        except Exception as e:
            logger.error(f"Failed to stream token: {e}")

    async def stream_tool_start(self, session_id: str, turn_id: str, tool_name: str, arguments: Dict[str, Any]):
        """Stream tool start event."""
        try:
            message = StreamingMessage(
                type="tool_start",
                data={"tool_name": tool_name, "arguments": arguments, "turn_id": turn_id},
                timestamp=datetime.utcnow().isoformat(),
                session_id=session_id,
                turn_id=turn_id,
            )
            await connection_manager.send_message(message, session_id)

        except Exception as e:
            logger.error(f"Failed to stream tool start: {e}")

    async def stream_tool_end(self, session_id: str, turn_id: str, tool_name: str, result: Any):
        """Stream tool end event."""
        try:
            message = StreamingMessage(
                type="tool_end",
                data={"tool_name": tool_name, "result": result, "turn_id": turn_id},
                timestamp=datetime.utcnow().isoformat(),
                session_id=session_id,
                turn_id=turn_id,
            )
            await connection_manager.send_message(message, session_id)

        except Exception as e:
            logger.error(f"Failed to stream tool end: {e}")

    async def stream_interrupt(self, session_id: str, turn_id: str, reason: str):
        """Stream interrupt event."""
        try:
            message = StreamingMessage(
                type="interrupt",
                data={"reason": reason, "turn_id": turn_id},
                timestamp=datetime.utcnow().isoformat(),
                session_id=session_id,
                turn_id=turn_id,
            )
            await connection_manager.send_message(message, session_id)

        except Exception as e:
            logger.error(f"Failed to stream interrupt: {e}")

    async def stream_error(self, session_id: str, turn_id: str, error: str):
        """Stream error event."""
        try:
            message = StreamingMessage(
                type="error",
                data={"error": error, "turn_id": turn_id},
                timestamp=datetime.utcnow().isoformat(),
                session_id=session_id,
                turn_id=turn_id,
            )
            await connection_manager.send_message(message, session_id)

        except Exception as e:
            logger.error(f"Failed to stream error: {e}")

    async def stream_complete(self, session_id: str, turn_id: str, response: str):
        """Stream complete event."""
        try:
            message = StreamingMessage(
                type="stream_complete",
                data={"response": response, "turn_id": turn_id},
                timestamp=datetime.utcnow().isoformat(),
                session_id=session_id,
                turn_id=turn_id,
            )
            await connection_manager.send_message(message, session_id)

        except Exception as e:
            logger.error(f"Failed to stream complete: {e}")

    async def _get_next_turn_number(self, session_id: str) -> int:
        """Get the next turn number for a session."""
        turns = await self.session_manager.get_session_turns(session_id)
        return len(turns) + 1

    async def get_active_streams(self) -> List[Dict[str, Any]]:
        """Get list of active streams."""
        try:
            active_streams = []
            for session_id, connections in connection_manager.active_connections.items():
                stream_info = {
                    "session_id": session_id,
                    "connection_count": len(connections),
                    "stream_queue_size": len(connection_manager.session_streams.get(session_id, [])),
                }
                active_streams.append(stream_info)
            
            return active_streams

        except Exception as e:
            logger.error(f"Failed to get active streams: {e}")
            return []


# Global instance
_streaming_manager = None


def get_streaming_manager() -> StreamingManager:
    """Get the global streaming manager instance."""
    global _streaming_manager
    if _streaming_manager is None:
        _streaming_manager = StreamingManager()
    return _streaming_manager


@router.websocket("/ws/stream/{session_id}")
async def websocket_stream(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for streaming."""
    await connection_manager.connect(websocket, session_id)
    try:
        while True:
            # Wait for incoming messages
            data = await websocket.receive_text()
            message = json.loads(data)
            
            # Handle different message types
            if message.get("type") == "start_stream":
                streaming_manager = get_streaming_manager()
                turn_id = await streaming_manager.start_stream(session_id, message["data"]["message"])
                
                # Send confirmation
                response = {
                    "type": "stream_confirmed",
                    "data": {"turn_id": turn_id},
                    "timestamp": datetime.utcnow().isoformat(),
                }
                await websocket.send_text(json.dumps(response))
            
            elif message.get("type") == "stream_data":
                # Handle streaming data from client
                pass
            
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket, session_id)


@router.post("/stream/{session_id}/start")
async def start_stream(session_id: str, message: Dict[str, str]):
    """Start a new stream for a session."""
    streaming_manager = get_streaming_manager()
    turn_id = await streaming_manager.start_stream(session_id, message["message"])
    return {"turn_id": turn_id, "message": "Stream started"}


@router.post("/stream/{session_id}/{turn_id}/token")
async def stream_token(session_id: str, turn_id: str, token: Dict[str, str]):
    """Stream a token to the session."""
    streaming_manager = get_streaming_manager()
    await streaming_manager.stream_token(session_id, turn_id, token["token"])
    return {"status": "success"}


@router.post("/stream/{session_id}/{turn_id}/tool/start")
async def stream_tool_start(
    session_id: str,
    turn_id: str,
    tool_data: Dict[str, Any]
):
    """Stream tool start event."""
    streaming_manager = get_streaming_manager()
    await streaming_manager.stream_tool_start(
        session_id,
        turn_id,
        tool_data["tool_name"],
        tool_data["arguments"]
    )
    return {"status": "success"}


@router.post("/stream/{session_id}/{turn_id}/tool/end")
async def stream_tool_end(
    session_id: str,
    turn_id: str,
    tool_data: Dict[str, Any]
):
    """Stream tool end event."""
    streaming_manager = get_streaming_manager()
    await streaming_manager.stream_tool_end(
        session_id,
        turn_id,
        tool_data["tool_name"],
        tool_data["result"]
    )
    return {"status": "success"}


@router.post("/stream/{session_id}/{turn_id}/interrupt")
async def stream_interrupt(session_id: str, turn_id: str, interrupt_data: Dict[str, str]):
    """Stream interrupt event."""
    streaming_manager = get_streaming_manager()
    await streaming_manager.stream_interrupt(session_id, turn_id, interrupt_data["reason"])
    return {"status": "success"}


@router.post("/stream/{session_id}/{turn_id}/error")
async def stream_error(session_id: str, turn_id: str, error_data: Dict[str, str]):
    """Stream error event."""
    streaming_manager = get_streaming_manager()
    await streaming_manager.stream_error(session_id, turn_id, error_data["error"])
    return {"status": "success"}


@router.post("/stream/{session_id}/{turn_id}/complete")
async def stream_complete(session_id: str, turn_id: str, complete_data: Dict[str, str]):
    """Stream complete event."""
    streaming_manager = get_streaming_manager()
    await streaming_manager.stream_complete(session_id, turn_id, complete_data["response"])
    return {"status": "success"}


@router.get("/stream/active")
async def get_active_streams():
    """Get list of active streams."""
    streaming_manager = get_streaming_manager()
    return await streaming_manager.get_active_streams()