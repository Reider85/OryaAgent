"""Next.js Web UI for B-11..B-15: chat interface, sidebar, settings, tool-call visualization, WebSocket streaming."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.security import get_current_user
from app.core.observability.spans import emit_span

logger = logging.getLogger(__name__)
router = APIRouter()
templates = Jinja2Templates(directory="app/ui/templates")


class WebSocketManager:
    """Manager for WebSocket connections."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    
    async def connect(self, websocket: WebSocket):
        """Accept a WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
    
    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        self.active_connections.remove(websocket)
    
    async def send_personal_message(self, message: str, websocket: WebSocket):
        """Send a personal message to a specific WebSocket."""
        await websocket.send_text(message)
    
    async def broadcast(self, message: str):
        """Broadcast a message to all connected WebSockets."""
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                # Connection might be closed
                pass


# Global WebSocket manager
websocket_manager = WebSocketManager()


@router.get("/", response_class=HTMLResponse)
async def chat_interface_ui(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Chat interface UI page."""
    try:
        return templates.TemplateResponse(
            "nextjs/chat.html",
            {
                "request": request,
                "current_user": current_user,
            },
        )
        
    except Exception as e:
        logger.error(f"Error in chat interface UI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load chat interface: {str(e)}")


@router.get("/sessions", response_class=HTMLResponse)
async def sessions_sidebar_ui(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Sessions sidebar UI page."""
    try:
        return templates.TemplateResponse(
            "nextjs/sessions.html",
            {
                "request": request,
                "current_user": current_user,
            },
        )
        
    except Exception as e:
        logger.error(f"Error in sessions sidebar UI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load sessions sidebar: {str(e)}")


@router.get("/settings", response_class=HTMLResponse)
async def settings_panel_ui(
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Settings panel UI page."""
    try:
        return templates.TemplateResponse(
            "nextjs/settings.html",
            {
                "request": request,
                "current_user": current_user,
            },
        )
        
    except Exception as e:
        logger.error(f"Error in settings panel UI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load settings panel: {str(e)}")


@router.get("/tool-calls", response_class=HTMLResponse)
async def tool_calls_visualization_ui(
    request: Request,
    session_id: str = None,
    current_user: str = Depends(get_current_user),
):
    """Tool calls visualization UI page."""
    try:
        return templates.TemplateResponse(
            "nextjs/tool_calls.html",
            {
                "request": request,
                "session_id": session_id,
                "current_user": current_user,
            },
        )
        
    except Exception as e:
        logger.error(f"Error in tool calls visualization UI: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to load tool calls visualization: {str(e)}")


@router.websocket("/ws/{session_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    session_id: str,
):
    """WebSocket endpoint for real-time communication."""
    await websocket_manager.connect(websocket)
    try:
        # Send initial connection message
        await websocket_manager.send_personal_message(
            json.dumps({
                "type": "connection",
                "message": "Connected to OryaAgent",
                "session_id": session_id,
            }),
            websocket
        )
        
        while True:
            # Wait for messages from client
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                
                # Handle different message types
                if message.get("type") == "message":
                    # Handle chat messages
                    await handle_chat_message(message, session_id, websocket)
                elif message.get("type") == "tool_call":
                    # Handle tool calls
                    await handle_tool_call(message, session_id, websocket)
                elif message.get("type") == "stream_request":
                    # Handle streaming requests
                    await handle_stream_request(message, session_id, websocket)
                else:
                    # Unknown message type
                    await websocket_manager.send_personal_message(
                        json.dumps({
                            "type": "error",
                            "message": f"Unknown message type: {message.get('type')}",
                        }),
                        websocket
                    )
                    
            except json.JSONDecodeError:
                await websocket_manager.send_personal_message(
                    json.dumps({
                        "type": "error",
                        "message": "Invalid JSON message",
                    }),
                    websocket
                )
                
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)


async def handle_chat_message(message: Dict[str, Any], session_id: str, websocket: WebSocket):
    """Handle chat messages from the client."""
    try:
        # Extract message data
        content = message.get("content", "")
        message_type = message.get("type", "user")
        
        # In a real implementation, this would:
        # 1. Send the message to the agent
        # 2. Get the response
        # 3. Stream the response back
        
        # For now, just echo the message
        await websocket_manager.send_personal_message(
            json.dumps({
                "type": "message_echo",
                "content": content,
                "message_type": message_type,
                "session_id": session_id,
            }),
            websocket
        )
        
    except Exception as e:
        logger.error(f"Error handling chat message: {e}")
        await websocket_manager.send_personal_message(
            json.dumps({
                "type": "error",
                "message": f"Error processing message: {str(e)}",
            }),
            websocket
        )


async def handle_tool_call(message: Dict[str, Any], session_id: str, websocket: WebSocket):
    """Handle tool calls from the client."""
    try:
        # Extract tool call data
        tool_name = message.get("tool_name")
        arguments = message.get("arguments", {})
        
        # In a real implementation, this would:
        # 1. Execute the tool
        # 2. Get the result
        # 3. Send the result back
        
        # For now, just simulate a tool call
        result = {
            "tool_name": tool_name,
            "arguments": arguments,
            "result": f"Simulated result for {tool_name}",
            "status": "completed",
        }
        
        await websocket_manager.send_personal_message(
            json.dumps({
                "type": "tool_call_result",
                "result": result,
                "session_id": session_id,
            }),
            websocket
        )
        
    except Exception as e:
        logger.error(f"Error handling tool call: {e}")
        await websocket_manager.send_personal_message(
            json.dumps({
                "type": "error",
                "message": f"Error processing tool call: {str(e)}",
            }),
            websocket
        )


async def handle_stream_request(message: Dict[str, Any], session_id: str, websocket: WebSocket):
    """Handle streaming requests from the client."""
    try:
        # Extract stream request data
        request_id = message.get("request_id")
        prompt = message.get("prompt")
        
        # In a real implementation, this would:
        # 1. Start a streaming response from the agent
        # 2. Send tokens as they arrive
        
        # For now, simulate streaming
        tokens = prompt.split()  # Simple tokenization
        for i, token in enumerate(tokens):
            await websocket_manager.send_personal_message(
                json.dumps({
                    "type": "stream_token",
                    "request_id": request_id,
                    "token": token,
                    "position": i,
                    "total_tokens": len(tokens),
                    "session_id": session_id,
                }),
                websocket
            )
            
            # Simulate delay
            import asyncio
            await asyncio.sleep(0.1)
        
        # Send stream completion
        await websocket_manager.send_personal_message(
            json.dumps({
                "type": "stream_complete",
                "request_id": request_id,
                "session_id": session_id,
            }),
            websocket
        )
        
    except Exception as e:
        logger.error(f"Error handling stream request: {e}")
        await websocket_manager.send_personal_message(
            json.dumps({
                "type": "error",
                "message": f"Error processing stream request: {str(e)}",
            }),
            websocket
        )


@router.get("/api/sessions")
async def get_sessions(
    current_user: str = Depends(get_current_user),
):
    """Get all sessions for the current user."""
    try:
        # In a real implementation, this would query the database
        # For now, return mock data
        sessions = [
            {
                "id": "session_1",
                "name": "Python Project",
                "created_at": "2024-01-15T10:00:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
                "turn_count": 15,
                "status": "active",
            },
            {
                "id": "session_2",
                "name": "JavaScript Development",
                "created_at": "2024-01-14T14:00:00Z",
                "updated_at": "2024-01-14T16:30:00Z",
                "turn_count": 8,
                "status": "completed",
            },
        ]
        
        return JSONResponse(content={"sessions": sessions})
        
    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get sessions: {str(e)}")


@router.post("/api/sessions")
async def create_session(
    current_user: str = Depends(get_current_user),
):
    """Create a new session."""
    try:
        # In a real implementation, this would create a session in the database
        # For now, return mock data
        new_session = {
            "id": f"session_{int(time.time())}",
            "name": f"New Session {int(time.time())}",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "turn_count": 0,
            "status": "active",
        }
        
        return JSONResponse(content=new_session, status_code=201)
        
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")


@router.get("/api/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Get messages for a specific session."""
    try:
        # In a real implementation, this would query the database
        # For now, return mock data
        messages = [
            {
                "id": "msg_1",
                "role": "user",
                "content": "Hello, I need help with my Python project.",
                "timestamp": "2024-01-15T10:00:00Z",
            },
            {
                "id": "msg_2",
                "role": "assistant",
                "content": "Hello! I'd be happy to help you with your Python project. What specific task would you like me to help you with?",
                "timestamp": "2024-01-15T10:00:05Z",
            },
        ]
        
        return JSONResponse(content={"messages": messages})
        
    except Exception as e:
        logger.error(f"Error getting session messages: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get session messages: {str(e)}")


@router.post("/api/sessions/{session_id}/messages")
async def send_message(
    session_id: str,
    request: Request,
    current_user: str = Depends(get_current_user),
):
    """Send a message to a session."""
    try:
        data = await request.json()
        content = data.get("content", "")
        
        # In a real implementation, this would:
        # 1. Send the message to the agent
        # 2. Get the response
        # 3. Store both in the database
        
        # For now, return mock response
        response = {
            "id": f"msg_{int(time.time())}",
            "role": "assistant",
            "content": f"I received your message: '{content}'. How can I help you?",
            "timestamp": datetime.utcnow().isoformat(),
        }
        
        return JSONResponse(content=response, status_code=201)
        
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")


# Helper function to initialize the UI router
def setup_nextjs_ui():
    """Setup Next.js UI routes."""
    return router