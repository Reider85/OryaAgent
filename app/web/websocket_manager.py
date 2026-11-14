"""Enhanced WebSocket manager for B-15 streaming functionality."""

import asyncio
import json
import logging
import time
from typing import Dict, List, Optional, Set
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from app.web.websocket_models import (
    WebSocketMessage,
    MessageType,
    ConnectionMessage,
    StatusMessage,
    serialize_message,
    parse_websocket_message,
)


logger = logging.getLogger(__name__)


class ConnectionInfo:
    """Information about a WebSocket connection."""
    
    def __init__(self, websocket: WebSocket, session_id: str, user_id: str):
        self.websocket = websocket
        self.session_id = session_id
        self.user_id = user_id
        self.connection_id = str(uuid4())
        self.connected_at = time.time()
        self.last_activity = time.time()
        self.message_count = 0
        self.is_active = True
        
    def update_activity(self):
        """Update last activity time."""
        self.last_activity = time.time()
        self.message_count += 1
        
    def get_duration(self) -> float:
        """Get connection duration in seconds."""
        return time.time() - self.connected_at
        
    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "connection_id": self.connection_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "connected_at": self.connected_at,
            "last_activity": self.last_activity,
            "message_count": self.message_count,
            "duration": self.get_duration(),
            "is_active": self.is_active,
        }


class EnhancedWebSocketManager:
    """Enhanced WebSocket manager with session management and reconnection."""
    
    def __init__(self, max_connections: int = 1000):
        self.max_connections = max_connections
        self.active_connections: Dict[str, ConnectionInfo] = {}  # connection_id -> ConnectionInfo
        self.session_connections: Dict[str, Set[str]] = {}  # session_id -> {connection_id}
        self.user_sessions: Dict[str, Set[str]] = {}  # user_id -> {session_id}
        self.connection_stats = {
            "total_connections": 0,
            "active_connections": 0,
            "total_messages": 0,
            "failed_connections": 0,
            "reconnections": 0,
        }
        
    async def connect(self, websocket: WebSocket, session_id: str, user_id: str) -> ConnectionInfo:
        """Connect a new WebSocket client."""
        # Check connection limit
        if len(self.active_connections) >= self.max_connections:
            raise WebSocketException("Maximum connections reached")
        
        # Accept the WebSocket connection
        await websocket.accept()
        
        # Create connection info
        connection_info = ConnectionInfo(websocket, session_id, user_id)
        
        # Store connection
        self.active_connections[connection_info.connection_id] = connection_info
        
        # Update session mapping
        if session_id not in self.session_connections:
            self.session_connections[session_id] = set()
        self.session_connections[session_id].add(connection_info.connection_id)
        
        # Update user session mapping
        if user_id not in self.user_sessions:
            self.user_sessions[user_id] = set()
        self.user_sessions[user_id].add(session_id)
        
        # Update stats
        self.connection_stats["total_connections"] += 1
        self.connection_stats["active_connections"] += 1
        
        # Send connection message
        await self.send_personal_message(
            ConnectionMessage.create(connection_info.connection_id, "connected"),
            connection_info.connection_id
        )
        
        logger.info(f"WebSocket connected: {connection_info.connection_id} (session: {session_id}, user: {user_id})")
        
        return connection_info
        
    async def disconnect(self, connection_id: str):
        """Disconnect a WebSocket client."""
        if connection_id not in self.active_connections:
            return
            
        connection_info = self.active_connections[connection_id]
        connection_info.is_active = False
        
        # Remove from active connections
        del self.active_connections[connection_id]
        
        # Remove from session mapping
        if connection_info.session_id in self.session_connections:
            self.session_connections[connection_info.session_id].discard(connection_id)
            if not self.session_connections[connection_info.session_id]:
                del self.session_connections[connection_info.session_id]
        
        # Remove from user session mapping (only if no other connections for this session)
        if connection_info.user_id in self.user_sessions:
            if connection_info.session_id in self.user_sessions[connection_info.user_id]:
                self.user_sessions[connection_info.user_id].discard(connection_info.session_id)
                if not self.user_sessions[connection_info.user_id]:
                    del self.user_sessions[connection_info.user_id]
        
        # Update stats
        self.connection_stats["active_connections"] -= 1
        
        # Send disconnection message
        try:
            await self.send_personal_message(
                ConnectionMessage.create(connection_info.connection_id, "disconnected"),
                connection_info.connection_id
            )
        except:
            pass  # Connection might already be closed
        
        logger.info(f"WebSocket disconnected: {connection_id}")
        
    async def send_personal_message(self, message: WebSocketMessage, connection_id: str):
        """Send a message to a specific connection."""
        if connection_id not in self.active_connections:
            raise WebSocketException(f"Connection {connection_id} not found")
        
        connection_info = self.active_connections[connection_id]
        try:
            await connection_info.websocket.send_text(serialize_message(message))
            connection_info.update_activity()
            self.connection_stats["total_messages"] += 1
        except WebSocketDisconnect:
            await self.disconnect(connection_id)
            raise
        except Exception as e:
            logger.error(f"Failed to send message to {connection_id}: {e}")
            await self.disconnect(connection_id)
            raise
            
    async def send_to_session(self, session_id: str, message: WebSocketMessage):
        """Send a message to all connections in a session."""
        if session_id not in self.session_connections:
            return
            
        connection_ids = list(self.session_connections[session_id])
        failed_connections = []
        
        for connection_id in connection_ids:
            try:
                await self.send_personal_message(message, connection_id)
            except Exception as e:
                logger.error(f"Failed to send message to {connection_id}: {e}")
                failed_connections.append(connection_id)
        
        # Clean up failed connections
        for connection_id in failed_connections:
            await self.disconnect(connection_id)
            
    async def send_to_user(self, user_id: str, message: WebSocketMessage):
        """Send a message to all sessions of a user."""
        if user_id not in self.user_sessions:
            return
            
        sessions = list(self.user_sessions[user_id])
        for session_id in sessions:
            await self.send_to_session(session_id, message)
            
    async def broadcast(self, message: WebSocketMessage):
        """Broadcast a message to all active connections."""
        connection_ids = list(self.active_connections.keys())
        failed_connections = []
        
        for connection_id in connection_ids:
            try:
                await self.send_personal_message(message, connection_id)
            except Exception as e:
                logger.error(f"Failed to broadcast message to {connection_id}: {e}")
                failed_connections.append(connection_id)
        
        # Clean up failed connections
        for connection_id in failed_connections:
            await self.disconnect(connection_id)
            
    async def handle_message(self, connection_id: str, message: WebSocketMessage):
        """Handle an incoming message from a connection."""
        if connection_id not in self.active_connections:
            raise WebSocketException(f"Connection {connection_id} not found")
        
        connection_info = self.active_connections[connection_id]
        connection_info.update_activity()
        
        # Route message based on type
        if message.type == MessageType.USER:
            # User messages are typically handled by the application logic
            logger.info(f"Received user message from {connection_id}: {message.content}")
        elif message.type == MessageType.ERROR:
            logger.error(f"Error from {connection_id}: {message.error_message}")
        else:
            logger.debug(f"Received {message.type} message from {connection_id}")
            
    async def get_connection_stats(self) -> dict:
        """Get connection statistics."""
        return {
            **self.connection_stats,
            "sessions": len(self.session_connections),
            "users": len(self.user_sessions),
            "connections_by_session": {
                session_id: len(connections) 
                for session_id, connections in self.session_connections.items()
            },
            "connections_by_user": {
                user_id: len(sessions)
                for user_id, sessions in self.user_sessions.items()
            },
        }
        
    async def get_session_connections(self, session_id: str) -> List[ConnectionInfo]:
        """Get all connections for a session."""
        if session_id not in self.session_connections:
            return []
            
        connection_ids = self.session_connections[session_id]
        return [
            self.active_connections[connection_id]
            for connection_id in connection_ids
            if connection_id in self.active_connections
        ]
        
    async def get_user_sessions(self, user_id: str) -> List[str]:
        """Get all sessions for a user."""
        if user_id not in self.user_sessions:
            return []
            
        return list(self.user_sessions[user_id])
        
    async def cleanup_inactive_connections(self, max_inactive_time: float = 300.0):
        """Clean up inactive connections."""
        current_time = time.time()
        inactive_connections = []
        
        for connection_id, connection_info in self.active_connections.items():
            if current_time - connection_info.last_activity > max_inactive_time:
                inactive_connections.append(connection_id)
        
        for connection_id in inactive_connections:
            logger.info(f"Cleaning up inactive connection: {connection_id}")
            await self.disconnect(connection_id)
            
    async def health_check(self) -> dict:
        """Perform health check on all connections."""
        stats = await self.get_connection_stats()
        
        # Check for any issues
        issues = []
        if stats["failed_connections"] > 0:
            issues.append(f"Failed connections: {stats['failed_connections']}")
        if stats["reconnections"] > stats["total_connections"] * 0.1:
            issues.append(f"High reconnection rate: {stats['reconnections']}/{stats['total_connections']}")
            
        return {
            "status": "healthy" if not issues else "degraded",
            "issues": issues,
            "stats": stats,
        }


class WebSocketException(Exception):
    """WebSocket-related exception."""
    pass


# Global WebSocket manager instance
websocket_manager = EnhancedWebSocketManager()


async def handle_websocket_connection(websocket: WebSocket, session_id: str, user_id: str):
    """Handle a WebSocket connection."""
    try:
        # Connect the client
        connection_info = await websocket_manager.connect(websocket, session_id, user_id)
        
        try:
            # Handle incoming messages
            while True:
                try:
                    # Wait for message with timeout
                    data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                    
                    try:
                        message = parse_websocket_message(data)
                        await websocket_manager.handle_message(connection_info.connection_id, message)
                    except ValueError as e:
                        logger.error(f"Invalid message from {connection_info.connection_id}: {e}")
                        await websocket_manager.send_personal_message(
                            WebSocketMessage(
                                type=MessageType.ERROR,
                                error_message=f"Invalid message: {e}",
                                session_id=session_id,
                            ),
                            connection_info.connection_id
                        )
                        
                except asyncio.TimeoutError:
                    # Send ping to keep connection alive
                    try:
                        await websocket.send_text(json.dumps({"type": "ping", "timestamp": time.time()}))
                    except:
                        break
                        
        except WebSocketDisconnect:
            pass
        except Exception as e:
            logger.error(f"Error handling WebSocket connection: {e}")
            
    except WebSocketException as e:
        logger.error(f"WebSocket connection failed: {e}")
        try:
            await websocket.close(code=1008, reason=str(e))
        except:
            pass
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket connection: {e}")
        try:
            await websocket.close(code=1011, reason="Internal server error")
        except:
            pass
    finally:
        await websocket_manager.disconnect(connection_info.connection_id)


# Reconnection logic with exponential backoff
class ReconnectionManager:
    """Manages WebSocket reconnection with exponential backoff."""
    
    def __init__(self, max_attempts: int = 5, base_delay: float = 3.0, max_delay: float = 30.0):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.reconnection_attempts: Dict[str, int] = {}
        
    async def handle_reconnection(self, connection_id: str, session_id: str, user_id: str) -> bool:
        """Handle reconnection with exponential backoff."""
        if connection_id not in self.reconnection_attempts:
            self.reconnection_attempts[connection_id] = 0
            
        attempts = self.reconnection_attempts[connection_id]
        
        if attempts >= self.max_attempts:
            logger.error(f"Max reconnection attempts reached for {connection_id}")
            return False
            
        # Calculate delay with exponential backoff
        delay = min(self.base_delay * (2 ** attempts), self.max_delay)
        
        logger.info(f"Reconnecting {connection_id} in {delay}s (attempt {attempts + 1}/{self.max_attempts})")
        
        await asyncio.sleep(delay)
        
        try:
            # Reset connection info
            self.reconnection_attempts[connection_id] = attempts + 1
            return True
        except Exception as e:
            logger.error(f"Reconnection failed for {connection_id}: {e}")
            return False
            
    def reset_attempts(self, connection_id: str):
        """Reset reconnection attempts for a connection."""
        if connection_id in self.reconnection_attempts:
            del self.reconnection_attempts[connection_id]


# Global reconnection manager
reconnection_manager = ReconnectionManager()