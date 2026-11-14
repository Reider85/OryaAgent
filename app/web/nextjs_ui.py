"""Next.js Web UI for B-11..B-15: chat interface, sidebar, settings, tool-call visualization, WebSocket streaming."""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.core.security import get_current_user
from app.core.observability.spans import emit_span
from app.ui.tool_visualization import router as tool_visualization_router

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
        raise HTTPException(
            status_code=500, detail=f"Failed to load chat interface: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Failed to load sessions sidebar: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Failed to load settings panel: {str(e)}"
        )


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
        raise HTTPException(
            status_code=500, detail=f"Failed to load tool calls visualization: {str(e)}"
        )


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
            json.dumps(
                {
                    "type": "connection",
                    "message": "Connected to OryaAgent",
                    "session_id": session_id,
                }
            ),
            websocket,
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
                        json.dumps(
                            {
                                "type": "error",
                                "message": f"Unknown message type: {message.get('type')}",
                            }
                        ),
                        websocket,
                    )

            except json.JSONDecodeError:
                await websocket_manager.send_personal_message(
                    json.dumps(
                        {
                            "type": "error",
                            "message": "Invalid JSON message",
                        }
                    ),
                    websocket,
                )

    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)


async def handle_chat_message(
    message: Dict[str, Any], session_id: str, websocket: WebSocket
):
    """Handle chat messages from the client."""
    try:
        # Extract message data
        content = message.get("content", "")
        user_id = message.get("user_id", "default_user")

        # Send user message back to confirm receipt
        await websocket_manager.send_personal_message(
            json.dumps(
                {
                    "type": "message",
                    "role": "user",
                    "content": content,
                    "timestamp": datetime.utcnow().isoformat(),
                    "session_id": session_id,
                }
            ),
            websocket,
        )

        # Process message through the agent
        await process_agent_message(content, session_id, user_id, websocket)

    except Exception as e:
        logger.error(f"Error handling chat message: {e}")
        await websocket_manager.send_personal_message(
            json.dumps(
                {
                    "type": "error",
                    "message": f"Error processing message: {str(e)}",
                    "timestamp": datetime.utcnow().isoformat(),
                    "session_id": session_id,
                }
            ),
            websocket,
        )


async def handle_tool_call(
    message: Dict[str, Any], session_id: str, websocket: WebSocket
):
    """Handle tool calls from the client."""
    try:
        # Extract tool call data
        tool_name = message.get("tool_name")
        arguments = message.get("arguments", {})
        tool_call_id = message.get("tool_call_id", f"tool_{int(time.time() * 1000)}")

        # Send tool call start message
        tool_call_message = {
            "type": "tool_call",
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "arguments": arguments,
            "start_time": datetime.utcnow().isoformat(),
            "status": "running",
            "session_id": session_id,
        }

        await websocket_manager.send_personal_message(
            json.dumps(tool_call_message),
            websocket,
        )

        # In a real implementation, this would:
        # 1. Execute the tool
        # 2. Get the result
        # 3. Send the result back
        
        # Simulate tool execution
        import asyncio
        await asyncio.sleep(0.1)  # Simulate processing time
        
        result = {
            "tool_name": tool_name,
            "arguments": arguments,
            "result": f"Simulated result for {tool_name}",
            "status": "completed",
        }

        # Send tool call result message
        tool_result_message = {
            "type": "tool_result",
            "tool_call_id": tool_call_id,
            "result": result,
            "end_time": datetime.utcnow().isoformat(),
            "duration_ms": 100,  # Simulated duration
            "session_id": session_id,
        }

        await websocket_manager.send_personal_message(
            json.dumps(tool_result_message),
            websocket,
        )

    except Exception as e:
        logger.error(f"Error handling tool call: {e}")
        await websocket_manager.send_personal_message(
            json.dumps(
                {
                    "type": "error",
                    "message": f"Error processing tool call: {str(e)}",
                    "session_id": session_id,
                }
            ),
            websocket,
        )


async def handle_stream_request(
    message: Dict[str, Any], session_id: str, websocket: WebSocket
):
    """Handle streaming requests from the client."""
    try:
        # Extract stream request data
        request_id = message.get("request_id")
        prompt = message.get("prompt")
        user_id = message.get("user_id", "default_user")

        # Send user message
        await websocket_manager.send_personal_message(
            json.dumps(
                {
                    "type": "message",
                    "role": "user",
                    "content": prompt,
                    "timestamp": datetime.utcnow().isoformat(),
                    "session_id": session_id,
                }
            ),
            websocket,
        )

        # Process message through the agent with streaming
        await process_agent_message(
            prompt, session_id, user_id, websocket, streaming=True
        )

    except Exception as e:
        logger.error(f"Error handling stream request: {e}")
        await websocket_manager.send_personal_message(
            json.dumps(
                {
                    "type": "error",
                    "message": f"Error processing stream request: {str(e)}",
                    "timestamp": datetime.utcnow().isoformat(),
                    "session_id": session_id,
                }
            ),
            websocket,
        )


# In-memory session storage (in production, use database)
sessions_db = {}
session_counter = 0


@router.get("/api/sessions")
async def get_sessions(
    current_user: str = Depends(get_current_user),
):
    """Get all sessions for the current user."""
    try:
        # In a real implementation, this would query the database
        # For now, return sessions from memory
        user_sessions = [
            {
                "id": session_id,
                "name": session_data.get("name", f"Session {session_id}"),
                "created_at": session_data.get(
                    "created_at", datetime.utcnow().isoformat()
                ),
                "updated_at": session_data.get(
                    "updated_at", datetime.utcnow().isoformat()
                ),
                "turn_count": session_data.get("turn_count", 0),
                "status": session_data.get("status", "active"),
            }
            for session_id, session_data in sessions_db.items()
            if session_data.get("user_id") == current_user
        ]

        return JSONResponse(content={"sessions": user_sessions})

    except Exception as e:
        logger.error(f"Error getting sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get sessions: {str(e)}")


@router.post("/api/sessions")
async def create_session(
    current_user: str = Depends(get_current_user),
):
    """Create a new session."""
    try:
        global session_counter
        session_counter += 1

        new_session = {
            "id": f"session_{session_counter}_{int(time.time())}",
            "name": f"New Session {session_counter}",
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "turn_count": 0,
            "status": "active",
            "user_id": current_user,
            "messages": [],
        }

        # Store in memory (in production, use database)
        sessions_db[new_session["id"]] = new_session

        return JSONResponse(content=new_session, status_code=201)

    except Exception as e:
        logger.error(f"Error creating session: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create session: {str(e)}"
        )


@router.get("/api/sessions/{session_id}/messages")
async def get_session_messages(
    session_id: str,
    current_user: str = Depends(get_current_user),
):
    """Get messages for a specific session."""
    try:
        # Check if session exists and belongs to user
        if session_id not in sessions_db:
            raise HTTPException(status_code=404, detail="Session not found")

        session = sessions_db[session_id]
        if session.get("user_id") != current_user:
            raise HTTPException(status_code=403, detail="Access denied")

        messages = session.get("messages", [])

        return JSONResponse(content={"messages": messages})

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session messages: {e}")
        raise HTTPException(
            status_code=500, detail=f"Failed to get session messages: {str(e)}"
        )


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

        # Check if session exists and belongs to user
        if session_id not in sessions_db:
            raise HTTPException(status_code=404, detail="Session not found")

        session = sessions_db[session_id]
        if session.get("user_id") != current_user:
            raise HTTPException(status_code=403, detail="Access denied")

        # Store user message
        user_message = {
            "id": f"msg_{int(time.time())}",
            "role": "user",
            "content": content,
            "timestamp": datetime.utcnow().isoformat(),
        }

        session["messages"].append(user_message)
        session["updated_at"] = datetime.utcnow().isoformat()
        session["turn_count"] += 1

        # Process the message through the agent
        # Note: This is a simplified version - in production, you'd want to handle this asynchronously
        try:
            from app.core.graph import build_graph
            from app.core.tools import get_tools

            tools = get_tools()
            graph = build_graph(
                tools=tools,
                model="haiku",
                checkpointer=None,
                policy=None,
                system_prompt_fn=None,
                trim_fn=None,
            )

            from langchain_core.messages import HumanMessage

            initial_message = HumanMessage(content=content)

            # Get response from agent
            response = await graph.ainvoke({"messages": [initial_message]})

            if response and "messages" in response:
                assistant_message = response["messages"][-1]
                if hasattr(assistant_message, "content") and assistant_message.content:
                    assistant_response = {
                        "id": f"msg_{int(time.time())}",
                        "role": "assistant",
                        "content": assistant_message.content,
                        "timestamp": datetime.utcnow().isoformat(),
                    }
                    session["messages"].append(assistant_response)
                    session["updated_at"] = datetime.utcnow().isoformat()

                    return JSONResponse(content=assistant_response, status_code=201)

        except Exception as e:
            logger.error(f"Error processing agent message: {e}")
            # Handle soft limits gracefully
            if "step" in str(e).lower() or "limit" in str(e).lower():
                assistant_response = {
                    "id": f"msg_{int(time.time())}",
                    "role": "assistant",
                    "content": "I've reached my processing limit for this conversation. Please provide a new instruction to continue.",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            else:
                assistant_response = {
                    "id": f"msg_{int(time.time())}",
                    "role": "assistant",
                    "content": f"I apologize, but I encountered an error processing your request: {str(e)}",
                    "timestamp": datetime.utcnow().isoformat(),
                }

            session["messages"].append(assistant_response)
            session["updated_at"] = datetime.utcnow().isoformat()

            return JSONResponse(content=assistant_response, status_code=201)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to send message: {str(e)}")


async def process_agent_message(
    content: str,
    session_id: str,
    user_id: str,
    websocket: WebSocket,
    streaming: bool = False,
):
    """Process a message through the OryaAgent."""
    try:
        # Import here to avoid circular imports
        from app.core.graph import build_graph
        from app.core.tools import get_tools
        from app.core.memory import get_md_store
        from app.core.config import get_settings

        settings = get_settings()

        # Get tools and build graph
        tools = get_tools()

        # Get or create session
        # In a real implementation, this would use the database session store
        # For now, we'll use a simple approach
        graph = build_graph(
            tools=tools,
            model="haiku",  # Default model for web UI
            checkpointer=None,  # No checkpointing for web UI
            policy=None,  # Use default policy
            system_prompt_fn=None,
            trim_fn=None,
        )

        # Create initial message
        from langchain_core.messages import HumanMessage

        initial_message = HumanMessage(content=content)

        # Process the message
        async for chunk in graph.astream(
            {"messages": [initial_message]}, stream_mode="values"
        ):
            # Handle different types of chunks
            if hasattr(chunk, "messages") and chunk.messages:
                for message in chunk.messages:
                    if hasattr(message, "content") and message.content:
                        # Send streaming response
                        await websocket_manager.send_personal_message(
                            json.dumps(
                                {
                                    "type": "message",
                                    "role": "assistant",
                                    "content": message.content,
                                    "timestamp": datetime.utcnow().isoformat(),
                                    "session_id": session_id,
                                }
                            ),
                            websocket,
                        )

            # Handle tool calls
            if hasattr(chunk, "messages") and chunk.messages:
                for message in chunk.messages:
                    if hasattr(message, "tool_calls") and message.tool_calls:
                        for tool_call in message.tool_calls:
                            await websocket_manager.send_personal_message(
                                json.dumps(
                                    {
                                        "type": "tool_call",
                                        "tool_name": tool_call.get("name"),
                                        "arguments": tool_call.get("args", {}),
                                        "timestamp": datetime.utcnow().isoformat(),
                                        "session_id": session_id,
                                    }
                                ),
                                websocket,
                            )

                            # Simulate tool execution
                            try:
                                # In a real implementation, this would execute the tool
                                tool_result = f"Executed {tool_call.get('name')} with {tool_call.get('args', {})}"

                                await websocket_manager.send_personal_message(
                                    json.dumps(
                                        {
                                            "type": "tool_result",
                                            "tool_name": tool_call.get("name"),
                                            "result": tool_result,
                                            "status": "completed",
                                            "timestamp": datetime.utcnow().isoformat(),
                                            "session_id": session_id,
                                        }
                                    ),
                                    websocket,
                                )
                            except Exception as e:
                                await websocket_manager.send_personal_message(
                                    json.dumps(
                                        {
                                            "type": "tool_result",
                                            "tool_name": tool_call.get("name"),
                                            "result": f"Error: {str(e)}",
                                            "status": "error",
                                            "timestamp": datetime.utcnow().isoformat(),
                                            "session_id": session_id,
                                        }
                                    ),
                                    websocket,
                                )

        # Send completion signal
        await websocket_manager.send_personal_message(
            json.dumps(
                {
                    "type": "stream_complete",
                    "session_id": session_id,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ),
            websocket,
        )

    except Exception as e:
        logger.error(f"Error processing agent message: {e}")
        # Handle soft limits - NO error indicators for soft limits
        if "step" in str(e).lower() or "limit" in str(e).lower():
            # Soft limit - send normal completion message
            await websocket_manager.send_personal_message(
                json.dumps(
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": "I've reached my processing limit for this conversation. Please provide a new instruction to continue.",
                        "timestamp": datetime.utcnow().isoformat(),
                        "session_id": session_id,
                    }
                ),
                websocket,
            )
        else:
            # Hard error - send error message
            await websocket_manager.send_personal_message(
                json.dumps(
                    {
                        "type": "error",
                        "message": f"Error processing your request: {str(e)}",
                        "timestamp": datetime.utcnow().isoformat(),
                        "session_id": session_id,
                    }
                ),
                websocket,
            )


# Include tool visualization router
router.include_router(tool_visualization_router, prefix="/ui")

# Helper function to initialize the UI router
def setup_nextjs_ui():
    """Setup Next.js UI routes."""
    return router
