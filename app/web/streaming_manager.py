"""Streaming manager for B-15 agent response streaming functionality."""

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional, AsyncGenerator
from uuid import uuid4

from app.web.websocket_models import (
    WebSocketMessage,
    MessageType,
    StreamTokenMessage,
    StreamCompleteMessage,
    ToolCallMessage,
    ToolResultMessage,
    AssistantMessage,
    serialize_message,
)


logger = logging.getLogger(__name__)


class StreamStats:
    """Statistics for a streaming session."""
    
    def __init__(self):
        self.start_time = time.time()
        self.tokens_sent = 0
        self.tools_called = 0
        self.tools_completed = 0
        self.errors = 0
        self.bytes_sent = 0
        
    def update(self, message_type: MessageType):
        """Update statistics based on message type."""
        if message_type == MessageType.STREAM_TOKEN:
            self.tokens_sent += 1
        elif message_type == MessageType.TOOL_CALL:
            self.tools_called += 1
        elif message_type == MessageType.TOOL_RESULT:
            self.tools_completed += 1
        elif message_type == MessageType.ERROR:
            self.errors += 1
            
    def get_duration(self) -> float:
        """Get stream duration in seconds."""
        return time.time() - self.start_time
        
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "start_time": self.start_time,
            "duration": self.get_duration(),
            "tokens_sent": self.tokens_sent,
            "tools_called": self.tools_called,
            "tools_completed": self.tools_completed,
            "errors": self.errors,
            "bytes_sent": self.bytes_sent,
        }


class StreamTask:
    """Represents an active streaming task."""
    
    def __init__(self, stream_id: str, session_id: str, user_id: str):
        self.stream_id = stream_id
        self.session_id = session_id
        self.user_id = user_id
        self.task: Optional[asyncio.Task] = None
        self.stats = StreamStats()
        self.is_active = False
        self.is_completed = False
        self.error: Optional[str] = None
        self.start_time = time.time()
        self.completion_time: Optional[float] = None
        
    def start(self, task: asyncio.Task):
        """Start the streaming task."""
        self.task = task
        self.is_active = True
        logger.info(f"Started streaming task {self.stream_id} for session {self.session_id}")
        
    def complete(self):
        """Mark the streaming task as completed."""
        self.is_active = False
        self.is_completed = True
        self.completion_time = time.time()
        logger.info(f"Completed streaming task {self.stream_id} in {self.get_duration():.2f}s")
        
    def cancel(self, reason: str = "Cancelled"):
        """Cancel the streaming task."""
        if self.task and not self.task.done():
            self.task.cancel()
        self.is_active = False
        self.error = reason
        logger.info(f"Cancelled streaming task {self.stream_id}: {reason}")
        
    def get_duration(self) -> float:
        """Get task duration in seconds."""
        if self.completion_time:
            return self.completion_time - self.start_time
        elif self.is_active:
            return time.time() - self.start_time
        else:
            return 0.0
            
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "stream_id": self.stream_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "is_active": self.is_active,
            "is_completed": self.is_completed,
            "error": self.error,
            "start_time": self.start_time,
            "completion_time": self.completion_time,
            "duration": self.get_duration(),
            "stats": self.stats.to_dict(),
        }


class StreamingManager:
    """Manager for agent response streaming with WebSocket integration."""
    
    def __init__(self, max_concurrent_streams: int = 100, max_stream_duration: float = 300.0):
        self.max_concurrent_streams = max_concurrent_streams
        self.max_stream_duration = max_stream_duration
        self.active_streams: Dict[str, StreamTask] = {}
        self.stream_stats = {
            "total_streams": 0,
            "active_streams": 0,
            "completed_streams": 0,
            "failed_streams": 0,
            "total_tokens": 0,
            "total_tools": 0,
        }
        
    async def start_stream_task(
        self, 
        session_id: str, 
        user_id: str, 
        message_generator: AsyncGenerator[str, None],
        websocket_manager
    ) -> str:
        """Start a new streaming task."""
        # Check stream limit
        if len(self.active_streams) >= self.max_concurrent_streams:
            raise StreamingException("Maximum concurrent streams reached")
        
        # Create stream task
        stream_id = str(uuid4())
        stream_task = StreamTask(stream_id, session_id, user_id)
        
        # Store stream
        self.active_streams[stream_id] = stream_task
        self.stream_stats["total_streams"] += 1
        self.stream_stats["active_streams"] += 1
        
        # Start the streaming coroutine
        task = asyncio.create_task(
            self._stream_tokens(stream_id, message_generator, websocket_manager)
        )
        stream_task.start(task)
        
        logger.info(f"Started stream {stream_id} for session {session_id}")
        
        return stream_id
        
    async def _stream_tokens(
        self, 
        stream_id: str, 
        message_generator: AsyncGenerator[str, None],
        websocket_manager
    ):
        """Stream tokens from generator to WebSocket connections."""
        stream_task = self.active_streams[stream_id]
        session_id = stream_task.session_id
        
        try:
            token_position = 0
            
            async for token in message_generator:
                # Check if stream is still active
                if not stream_task.is_active:
                    break
                    
                # Check stream duration
                if stream_task.get_duration() > self.max_stream_duration:
                    logger.warning(f"Stream {stream_id} exceeded maximum duration")
                    break
                
                # Create and send token message
                token_message = StreamTokenMessage.create(
                    token=token,
                    position=token_position,
                    session_id=session_id,
                )
                
                # Update statistics
                stream_task.stats.update(MessageType.STREAM_TOKEN)
                stream_task.stats.bytes_sent += len(token)
                self.stream_stats["total_tokens"] += 1
                
                # Send to session
                await websocket_manager.send_to_session(session_id, token_message)
                
                token_position += 1
                
            # Send completion message
            if stream_task.is_active:
                completion_message = StreamCompleteMessage.create(session_id)
                await websocket_manager.send_to_session(session_id, completion_message)
                stream_task.stats.update(MessageType.STREAM_COMPLETE)
                
        except asyncio.CancelledError:
            logger.info(f"Stream {stream_id} was cancelled")
            raise
        except Exception as e:
            logger.error(f"Error in stream {stream_id}: {e}")
            stream_task.error = str(e)
            
            # Send error message
            error_message = WebSocketMessage(
                type=MessageType.ERROR,
                error_message=str(e),
                session_id=session_id,
            )
            await websocket_manager.send_to_session(session_id, error_message)
            stream_task.stats.update(MessageType.ERROR)
            self.stream_stats["failed_streams"] += 1
            
        finally:
            # Clean up stream
            await self._cleanup_stream(stream_id)
            
    async def _cleanup_stream(self, stream_id: str):
        """Clean up a completed stream."""
        if stream_id not in self.active_streams:
            return
            
        stream_task = self.active_streams[stream_id]
        
        if not stream_task.is_completed:
            stream_task.complete()
            
        # Update statistics
        self.stream_stats["active_streams"] -= 1
        if stream_task.error:
            self.stream_stats["failed_streams"] += 1
        else:
            self.stream_stats["completed_streams"] += 1
            
        # Remove from active streams
        del self.active_streams[stream_id]
        
        logger.info(f"Cleaned up stream {stream_id}")
        
    async def cancel_stream(self, stream_id: str, reason: str = "Cancelled"):
        """Cancel a streaming task."""
        if stream_id not in self.active_streams:
            return
            
        stream_task = self.active_streams[stream_id]
        stream_task.cancel(reason)
        
        # Wait for task to complete
        try:
            await stream_task.task
        except asyncio.CancelledError:
            pass
            
    async def get_stream_stats(self, stream_id: str) -> Optional[dict]:
        """Get statistics for a specific stream."""
        if stream_id not in self.active_streams:
            return None
            
        return self.active_streams[stream_id].to_dict()
        
    async def get_all_streams_stats(self) -> dict:
        """Get statistics for all streams."""
        return {
            "active_streams": len(self.active_streams),
            "total_streams": self.stream_stats["total_streams"],
            "completed_streams": self.stream_stats["completed_streams"],
            "failed_streams": self.stream_stats["failed_streams"],
            "total_tokens": self.stream_stats["total_tokens"],
            "total_tools": self.stream_stats["total_tools"],
            "streams": [
                stream_task.to_dict()
                for stream_task in self.active_streams.values()
            ],
        }
        
    async def cleanup_inactive_streams(self):
        """Clean up inactive or expired streams."""
        current_time = time.time()
        expired_streams = []
        
        for stream_id, stream_task in self.active_streams.items():
            if (current_time - stream_task.start_time > self.max_stream_duration or 
                not stream_task.is_active):
                expired_streams.append(stream_id)
                
        for stream_id in expired_streams:
            logger.info(f"Cleaning up expired stream {stream_id}")
            await self.cancel_stream(stream_id, "Stream expired")
            
    async def health_check(self) -> dict:
        """Perform health check on streaming manager."""
        stats = await self.get_all_streams_stats()
        
        # Check for any issues
        issues = []
        if stats["failed_streams"] > stats["total_streams"] * 0.1:
            issues.append(f"High failure rate: {stats['failed_streams']}/{stats['total_streams']}")
        if stats["active_streams"] > self.max_concurrent_streams * 0.9:
            issues.append(f"High stream load: {stats['active_streams']}/{self.max_concurrent_streams}")
            
        return {
            "status": "healthy" if not issues else "degraded",
            "issues": issues,
            "stats": stats,
        }


class StreamingException(Exception):
    """Streaming-related exception."""
    pass


# Mock agent response generator for testing
async def mock_agent_response_generator(message: str) -> AsyncGenerator[str, None]:
    """Mock agent response generator for testing purposes."""
    # Simulate processing time
    await asyncio.sleep(0.1)
    
    # Echo the message with some processing
    response = f"You said: {message}"
    
    # Stream character by character
    for char in response:
        yield char
        await asyncio.sleep(0.05)  # Simulate token generation time
        
    # Simulate a tool call
    await asyncio.sleep(0.5)
    yield "\n\n"
    yield "Calling tool: read_file"
    yield "\n"
    yield "Tool arguments: {'path': 'example.txt'}"
    yield "\n\n"
    yield "Tool result: File content read successfully"
    yield "\n\n"
    yield "Processing complete!"


# Enhanced streaming manager with tool call simulation
class EnhancedStreamingManager(StreamingManager):
    """Enhanced streaming manager with tool call visualization."""
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.active_tools: Dict[str, Dict] = {}  # tool_call_id -> tool_info
        
    async def simulate_tool_call(
        self, 
        session_id: str, 
        tool_name: str, 
        tool_args: Dict[str, Any],
        websocket_manager
    ) -> str:
        """Simulate a tool call and send tool visualization messages."""
        tool_call_id = str(uuid4())
        
        # Store tool info
        self.active_tools[tool_call_id] = {
            "tool_name": tool_name,
            "tool_args": tool_args,
            "start_time": time.time(),
            "session_id": session_id,
        }
        
        # Send tool call message
        tool_call_message = ToolCallMessage.create(
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
            session_id=session_id,
        )
        
        await websocket_manager.send_to_session(session_id, tool_call_message)
        self.stream_stats["total_tools"] += 1
        
        # Simulate tool execution
        await asyncio.sleep(1.0)
        
        # Send tool result message
        tool_result_message = ToolResultMessage.create(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            result={"status": "success", "output": "Tool executed successfully"},
            duration_ms=1000,
            session_id=session_id,
        )
        
        await websocket_manager.send_to_session(session_id, tool_result_message)
        
        # Clean up tool info
        del self.active_tools[tool_call_id]
        
        return tool_call_id
        
    async def get_active_tools(self) -> List[Dict]:
        """Get list of active tool calls."""
        return list(self.active_tools.values())


# Global streaming manager instance
streaming_manager = EnhancedStreamingManager()