"""Next.js Web UI: chat interface (B-11) - parallel to Chainlit.

Provides a web-based chat interface for OryaAgent sessions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.core.branch_manager import get_branch_manager
from app.core.session import SessionManager
from app.core.skills import get_skill_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["nextjs-web-ui"])


class ChatMessage(BaseModel):
    """Chat message model."""

    role: str
    content: str
    timestamp: str


class ChatSession(BaseModel):
    """Chat session model."""

    id: str
    name: str
    created_at: str
    messages: List[ChatMessage]


class ConnectionManager:
    """Manager for WebSocket connections."""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, session_id: str):
        """Accept a WebSocket connection."""
        await websocket.accept()
        if session_id not in self.active_connections:
            self.active_connections[session_id] = []
        self.active_connections[session_id].append(websocket)

    def disconnect(self, websocket: WebSocket, session_id: str):
        """Disconnect a WebSocket connection."""
        if session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]

    async def broadcast(self, message: str, session_id: str):
        """Broadcast a message to all connections in a session."""
        if session_id in self.active_connections:
            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_text(message)
                except Exception as e:
                    logger.error(f"Failed to send message to WebSocket: {e}")


connection_manager = ConnectionManager()


class ChatInterface:
    """Chat interface for Next.js Web UI."""

    def __init__(self):
        self.session_manager = SessionManager()
        self.branch_manager = get_branch_manager()
        self.skill_registry = get_skill_registry()
        self.templates = Jinja2Templates(directory="app/ui/templates")

    async def create_session(self, name: str = None) -> str:
        """Create a new chat session."""
        session_id = await self.session_manager.create_session(
            {"name": name or "New Chat"}
        )
        return session_id

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session information."""
        return await self.session_manager.get_session(session_id)

    async def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Get messages for a session."""
        turns = await self.session_manager.get_session_turns(session_id)
        messages = []
        for turn in turns:
            for message in turn["messages"]:
                messages.append(
                    {
                        "id": message.get("id"),
                        "role": message.get("role"),
                        "content": message.get("content"),
                        "timestamp": turn.get("created_at"),
                    }
                )
        return messages

    async def send_message(self, session_id: str, message: str) -> Dict[str, Any]:
        """Send a message to a session."""
        # This would integrate with the LangGraph agent
        # For now, return a placeholder response
        return {
            "session_id": session_id,
            "message": message,
            "response": f"Received: {message}",
            "timestamp": "2024-01-01T00:00:00Z",
        }

    async def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions."""
        sessions = await self.session_manager.list_sessions()
        return [
            {"id": s["id"], "name": s["name"], "created_at": s["created_at"]}
            for s in sessions
        ]

    async def list_skills(self) -> List[Dict[str, Any]]:
        """List available skills."""
        skills = self.skill_registry.list_skills()
        return [
            {"name": skill.name, "description": skill.description} for skill in skills
        ]

    async def activate_skill(self, session_id: str, skill_name: str) -> Dict[str, Any]:
        """Activate a skill for a session."""
        try:
            result = self.skill_registry.activate_skill(skill_name)
            return {"skill": skill_name, "result": result}
        except Exception as e:
            return {"skill": skill_name, "error": str(e)}

    async def create_branch(
        self, session_id: str, turn_id: str = None, branch_name: str = None
    ) -> str:
        """Create a branch from a session."""
        return await self.branch_manager.fork_session(session_id, turn_id, branch_name)

    async def list_branches(self, session_id: str) -> List[Dict[str, Any]]:
        """List branches for a session."""
        return await self.branch_manager.list_branches(session_id)


# Global instance
_chat_interface = None


def get_chat_interface() -> ChatInterface:
    """Get the global chat interface instance."""
    global _chat_interface
    if _chat_interface is None:
        _chat_interface = ChatInterface()
    return _chat_interface


@router.get("/chat", response_class=HTMLResponse)
async def chat_page(request):
    """Serve the chat page."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>OryaAgent Chat</title>
        <script src="https://cdn.tailwindcss.com"></script>
    </head>
    <body class="bg-gray-100">
        <div class="container mx-auto px-4 py-8">
            <h1 class="text-3xl font-bold mb-6">OryaAgent Chat</h1>
            <div id="chat-container" class="bg-white rounded-lg shadow-lg p-6 h-96 overflow-y-auto">
                <div id="messages"></div>
            </div>
            <div class="mt-4">
                <input type="text" id="message-input" class="w-full px-4 py-2 border rounded-lg" placeholder="Type your message...">
                <button id="send-button" class="mt-2 bg-blue-500 text-white px-4 py-2 rounded-lg">Send</button>
            </div>
        </div>
        <script>
            const sessionId = 'demo-session';
            const messagesContainer = document.getElementById('messages');
            const messageInput = document.getElementById('message-input');
            const sendButton = document.getElementById('send-button');

            // Load messages
            async function loadMessages() {
                try {
                    const response = await fetch(`/ui/api/chat/${sessionId}/messages`);
                    const messages = await response.json();
                    messagesContainer.innerHTML = '';
                    messages.forEach(msg => {
                        const messageDiv = document.createElement('div');
                        messageDiv.className = `mb-4 ${msg.role === 'user' ? 'text-right' : 'text-left'}`;
                        messageDiv.innerHTML = `
                            <div class="inline-block px-4 py-2 rounded-lg ${msg.role === 'user' ? 'bg-blue-500 text-white' : 'bg-gray-200 text-gray-800'}">
                                <div class="text-sm text-gray-500">${new Date(msg.timestamp).toLocaleTimeString()}</div>
                                <div>${msg.content}</div>
                            </div>
                        `;
                        messagesContainer.appendChild(messageDiv);
                    });
                } catch (error) {
                    console.error('Failed to load messages:', error);
                }
            }

            // Send message
            async function sendMessage() {
                const message = messageInput.value.trim();
                if (!message) return;

                // Add user message
                const userMessage = document.createElement('div');
                userMessage.className = 'mb-4 text-right';
                userMessage.innerHTML = `
                    <div class="inline-block px-4 py-2 rounded-lg bg-blue-500 text-white">
                        <div class="text-sm text-gray-500">${new Date().toLocaleTimeString()}</div>
                        <div>${message}</div>
                    </div>
                `;
                messagesContainer.appendChild(userMessage);

                // Clear input
                messageInput.value = '';

                // Send to server
                try {
                    const response = await fetch(`/ui/api/chat/${sessionId}/messages`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ content: message })
                    });
                    const result = await response.json();
                    
                    // Add response message
                    const responseMessage = document.createElement('div');
                    responseMessage.className = 'mb-4 text-left';
                    responseMessage.innerHTML = `
                        <div class="inline-block px-4 py-2 rounded-lg bg-gray-200 text-gray-800">
                            <div class="text-sm text-gray-500">${new Date(result.timestamp).toLocaleTimeString()}</div>
                            <div>${result.response}</div>
                        </div>
                    `;
                    messagesContainer.appendChild(responseMessage);
                    
                    // Scroll to bottom
                    messagesContainer.scrollTop = messagesContainer.scrollHeight;
                } catch (error) {
                    console.error('Failed to send message:', error);
                }
            }

            // Event listeners
            sendButton.addEventListener('click', sendMessage);
            messageInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') sendMessage();
            });

            // Initial load
            loadMessages();
        </script>
    </body>
    </html>
    """


@router.get("/api/chat/sessions")
async def list_sessions():
    """List all chat sessions."""
    chat_interface = get_chat_interface()
    return await chat_interface.list_sessions()


@router.post("/api/chat/sessions")
async def create_session(name: str = None):
    """Create a new chat session."""
    chat_interface = get_chat_interface()
    session_id = await chat_interface.create_session(name)
    return {"id": session_id, "name": name or "New Chat"}


@router.get("/api/chat/{session_id}/messages")
async def get_messages(session_id: str):
    """Get messages for a session."""
    chat_interface = get_chat_interface()
    messages = await chat_interface.get_session_messages(session_id)
    return messages


@router.post("/api/chat/{session_id}/messages")
async def send_message(session_id: str, message: Dict[str, str]):
    """Send a message to a session."""
    chat_interface = get_chat_interface()
    result = await chat_interface.send_message(session_id, message["content"])
    return result


@router.get("/api/chat/{session_id}/skills")
async def list_skills(session_id: str):
    """List available skills for a session."""
    chat_interface = get_chat_interface()
    skills = await chat_interface.list_skills()
    return skills


@router.post("/api/chat/{session_id}/skills/{skill_name}/activate")
async def activate_skill(session_id: str, skill_name: str):
    """Activate a skill for a session."""
    chat_interface = get_chat_interface()
    result = await chat_interface.activate_skill(session_id, skill_name)
    return result


@router.post("/api/chat/{session_id}/branches")
async def create_branch(session_id: str, turn_id: str = None, branch_name: str = None):
    """Create a branch from a session."""
    chat_interface = get_chat_interface()
    branch_id = await chat_interface.create_branch(session_id, turn_id, branch_name)
    return {"id": branch_id, "message": "Branch created successfully"}


@router.get("/api/chat/{session_id}/branches")
async def list_branches(session_id: str):
    """List branches for a session."""
    chat_interface = get_chat_interface()
    branches = await chat_interface.list_branches(session_id)
    return branches


@router.websocket("/ws/chat/{session_id}")
async def websocket_chat(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time chat."""
    await connection_manager.connect(websocket, session_id)
    try:
        while True:
            data = await websocket.receive_text()
            # Handle incoming messages and broadcast responses
            await connection_manager.broadcast(f"Echo: {data}", session_id)
    except WebSocketDisconnect:
        connection_manager.disconnect(websocket, session_id)
