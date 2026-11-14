"""Enhanced Next.js UI endpoint with B-15 WebSocket streaming functionality."""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.api.sessions import router as sessions_router
from app.core.auth import get_current_user
from app.core.config import get_settings
from app.db.session import get_async_session
from app.web.websocket_manager import websocket_manager, handle_websocket_connection
from app.web.streaming_manager import streaming_manager, mock_agent_response_generator

logger = logging.getLogger(__name__)

# Create router
router = APIRouter()
security = HTTPBearer()


@router.get("/", response_class=HTMLResponse)
async def get_chat_interface():
    """Get the chat interface HTML page."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OryaAgent - Chat Interface</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
            .container { max-width: 800px; margin: 0 auto; }
            .chat-container { border: 1px solid #ccc; height: 500px; overflow-y: auto; padding: 10px; margin-bottom: 10px; }
            .message { margin-bottom: 10px; padding: 10px; border-radius: 5px; }
            .user-message { background-color: #e3f2fd; }
            .assistant-message { background-color: #f1f8e9; }
            .error-message { background-color: #ffebee; }
            .tool-call { background-color: #fff3e0; }
            .tool-result { background-color: #e8f5e8; }
            .input-container { display: flex; gap: 10px; }
            input { flex: 1; padding: 10px; border: 1px solid #ccc; border-radius: 5px; }
            button { padding: 10px 20px; background-color: #2196f3; color: white; border: none; border-radius: 5px; cursor: pointer; }
            button:hover { background-color: #1976d2; }
            .status { margin-top: 10px; padding: 10px; border-radius: 5px; }
            .connected { background-color: #e8f5e8; }
            .disconnected { background-color: #ffebee; }
            .reconnecting { background-color: #fff3e0; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>OryaAgent Chat Interface</h1>
            <div id="status" class="status disconnected">Disconnected</div>
            <div id="chat-container" class="chat-container"></div>
            <div class="input-container">
                <input type="text" id="message-input" placeholder="Type your message..." />
                <button onclick="sendMessage()">Send</button>
            </div>
        </div>

        <script>
            let ws = null;
            let sessionId = null;
            let userId = null;
            let reconnectAttempts = 0;
            const maxReconnectAttempts = 5;

            // Initialize connection
            async function initializeConnection() {
                try {
                    // Get user session (simplified for demo)
                    const response = await fetch('/web/api/sessions', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                    });
                    
                    if (response.ok) {
                        const data = await response.json();
                        sessionId = data.id;
                        userId = 'demo_user';
                        
                        // Connect to WebSocket
                        connectWebSocket();
                    } else {
                        console.error('Failed to create session');
                    }
                } catch (error) {
                    console.error('Error initializing connection:', error);
                }
            }

            // Connect to WebSocket
            function connectWebSocket() {
                const wsUrl = `ws://localhost:8000/web/ws/${sessionId}`;
                ws = new WebSocket(wsUrl);

                ws.onopen = function(event) {
                    console.log('WebSocket connected');
                    updateStatus('connected', 'Connected');
                    reconnectAttempts = 0;
                };

                ws.onmessage = function(event) {
                    const message = JSON.parse(event.data);
                    handleWebSocketMessage(message);
                };

                ws.onclose = function(event) {
                    console.log('WebSocket disconnected');
                    updateStatus('disconnected', 'Disconnected');
                    
                    // Attempt to reconnect
                    if (reconnectAttempts < maxReconnectAttempts) {
                        reconnectAttempts++;
                        const delay = Math.min(1000 * Math.pow(2, reconnectAttempts), 30000);
                        console.log(`Reconnecting in ${delay}ms (attempt ${reconnectAttempts})`);
                        updateStatus('reconnecting', `Reconnecting... (${reconnectAttempts}/${maxReconnectAttempts})`);
                        
                        setTimeout(() => {
                            connectWebSocket();
                        }, delay);
                    } else {
                        console.error('Max reconnection attempts reached');
                    }
                };

                ws.onerror = function(error) {
                    console.error('WebSocket error:', error);
                    updateStatus('disconnected', 'Connection Error');
                };
            }

            // Handle WebSocket messages
            function handleWebSocketMessage(message) {
                console.log('Received message:', message);
                
                const chatContainer = document.getElementById('chat-container');
                const messageDiv = document.createElement('div');
                messageDiv.className = `message ${message.type}-message`;
                
                let content = '';
                switch (message.type) {
                    case 'user':
                        content = `<strong>You:</strong> ${message.content}`;
                        break;
                    case 'assistant':
                        content = `<strong>Assistant:</strong> ${message.content}`;
                        break;
                    case 'tool_call':
                        content = `<strong>Tool Call:</strong> ${message.tool_name}<br>Args: ${JSON.stringify(message.tool_args)}`;
                        break;
                    case 'tool_result':
                        content = `<strong>Tool Result:</strong> ${JSON.stringify(message.result)}`;
                        break;
                    case 'stream_token':
                        content = `<strong>Token:</strong> ${message.content}`;
                        break;
                    case 'error':
                        content = `<strong>Error:</strong> ${message.error_message}`;
                        break;
                    default:
                        content = `<strong>Message:</strong> ${JSON.stringify(message)}`;
                }
                
                messageDiv.innerHTML = content;
                chatContainer.appendChild(messageDiv);
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }

            // Send message
            async function sendMessage() {
                const input = document.getElementById('message-input');
                const message = input.value.trim();
                
                if (message && ws && ws.readyState === WebSocket.OPEN) {
                    // Send user message
                    const userMessage = {
                        id: Date.now().toString(),
                        type: 'user',
                        content: message,
                        timestamp: new Date().toISOString(),
                        session_id: sessionId
                    };
                    
                    ws.send(JSON.stringify(userMessage));
                    
                    // Clear input
                    input.value = '';
                    
                    // Simulate agent response
                    simulateAgentResponse(message);
                }
            }

            // Simulate agent response
            async function simulateAgentResponse(userMessage) {
                if (!ws || ws.readyState !== WebSocket.OPEN) {
                    return;
                }
                
                // Send assistant message
                const assistantMessage = {
                    id: Date.now().toString(),
                    type: 'assistant',
                    content: `You said: ${userMessage}`,
                    timestamp: new Date().toISOString(),
                    session_id: sessionId
                };
                
                ws.send(JSON.stringify(assistantMessage));
            }

            // Update status
            function updateStatus(status, text) {
                const statusDiv = document.getElementById('status');
                statusDiv.className = `status ${status}`;
                statusDiv.textContent = text;
            }

            // Handle Enter key
            document.getElementById('message-input').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    sendMessage();
                }
            });

            // Initialize on page load
            window.addEventListener('load', initializeConnection);
        </script>
    </body>
    </html>
    """


@router.get("/sessions", response_class=HTMLResponse)
async def get_sessions_interface():
    """Get the sessions management interface HTML page."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OryaAgent - Sessions</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
            .container { max-width: 800px; margin: 0 auto; }
            .session-list { border: 1px solid #ccc; padding: 10px; margin-bottom: 10px; }
            .session-item { padding: 10px; border-bottom: 1px solid #eee; cursor: pointer; }
            .session-item:hover { background-color: #f5f5f5; }
            .create-session { margin-bottom: 20px; }
            button { padding: 10px 20px; background-color: #2196f3; color: white; border: none; border-radius: 5px; cursor: pointer; }
            button:hover { background-color: #1976d2; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Sessions</h1>
            <div class="create-session">
                <button onclick="createSession()">Create New Session</button>
            </div>
            <div id="session-list" class="session-list"></div>
        </div>

        <script>
            async function loadSessions() {
                try {
                    const response = await fetch('/web/api/sessions');
                    if (response.ok) {
                        const data = await response.json();
                        displaySessions(data.sessions);
                    }
                } catch (error) {
                    console.error('Error loading sessions:', error);
                }
            }

            function displaySessions(sessions) {
                const sessionList = document.getElementById('session-list');
                sessionList.innerHTML = '';
                
                sessions.forEach(session => {
                    const sessionItem = document.createElement('div');
                    sessionItem.className = 'session-item';
                    sessionItem.innerHTML = `
                        <strong>Session:</strong> ${session.id}<br>
                        <strong>Name:</strong> ${session.name}<br>
                        <strong>Created:</strong> ${new Date(session.created_at).toLocaleString()}
                    `;
                    sessionItem.onclick = () => window.location.href = `/web/chat?session_id=${session.id}`;
                    sessionList.appendChild(sessionItem);
                });
            }

            async function createSession() {
                try {
                    const response = await fetch('/web/api/sessions', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                        },
                    });
                    
                    if (response.ok) {
                        loadSessions();
                    }
                } catch (error) {
                    console.error('Error creating session:', error);
                }
            }

            // Load sessions on page load
            window.addEventListener('load', loadSessions);
        </script>
    </body>
    </html>
    """


@router.get("/settings", response_class=HTMLResponse)
async def get_settings_interface():
    """Get the settings interface HTML page."""
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>OryaAgent - Settings</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
            .container { max-width: 800px; margin: 0 auto; }
            .settings-group { margin-bottom: 20px; padding: 20px; border: 1px solid #ccc; border-radius: 5px; }
            .setting-item { margin-bottom: 15px; }
            label { display: block; margin-bottom: 5px; font-weight: bold; }
            input, select, textarea { width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 5px; }
            button { padding: 10px 20px; background-color: #2196f3; color: white; border: none; border-radius: 5px; cursor: pointer; }
            button:hover { background-color: #1976d2; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Settings</h1>
            
            <div class="settings-group">
                <h2>WebSocket Settings</h2>
                <div class="setting-item">
                    <label for="ws-url">WebSocket URL:</label>
                    <input type="text" id="ws-url" value="ws://localhost:8000" />
                </div>
                <div class="setting-item">
                    <label for="reconnect-attempts">Max Reconnect Attempts:</label>
                    <input type="number" id="reconnect-attempts" value="5" min="1" max="10" />
                </div>
                <div class="setting-item">
                    <label for="reconnect-delay">Base Reconnect Delay (ms):</label>
                    <input type="number" id="reconnect-delay" value="3000" min="1000" max="10000" />
                </div>
            </div>
            
            <div class="settings-group">
                <h2>Streaming Settings</h2>
                <div class="setting-item">
                    <label for="max-concurrent-streams">Max Concurrent Streams:</label>
                    <input type="number" id="max-concurrent-streams" value="100" min="1" max="1000" />
                </div>
                <div class="setting-item">
                    <label for="max-stream-duration">Max Stream Duration (seconds):</label>
                    <input type="number" id="max-stream-duration" value="300" min="60" max="3600" />
                </div>
            </div>
            
            <div class="settings-group">
                <h2>General Settings</h2>
                <div class="setting-item">
                    <label for="log-level">Log Level:</label>
                    <select id="log-level">
                        <option value="DEBUG">Debug</option>
                        <option value="INFO" selected>Info</option>
                        <option value="WARNING">Warning</option>
                        <option value="ERROR">Error</option>
                    </select>
                </div>
                <div class="setting-item">
                    <label for="theme">Theme:</label>
                    <select id="theme">
                        <option value="light">Light</option>
                        <option value="dark">Dark</option>
                        <option value="auto">Auto</option>
                    </select>
                </div>
            </div>
            
            <button onclick="saveSettings()">Save Settings</button>
        </div>

        <script>
            function saveSettings() {
                const settings = {
                    ws_url: document.getElementById('ws-url').value,
                    reconnect_attempts: document.getElementById('reconnect-attempts').value,
                    reconnect_delay: document.getElementById('reconnect-delay').value,
                    max_concurrent_streams: document.getElementById('max-concurrent-streams').value,
                    max_stream_duration: document.getElementById('max-stream-duration').value,
                    log_level: document.getElementById('log-level').value,
                    theme: document.getElementById('theme').value,
                };
                
                // Save to localStorage
                localStorage.setItem('orya_settings', JSON.stringify(settings));
                
                alert('Settings saved successfully!');
            }
            
            // Load settings on page load
            window.addEventListener('load', function() {
                const savedSettings = localStorage.getItem('orya_settings');
                if (savedSettings) {
                    const settings = JSON.parse(savedSettings);
                    document.getElementById('ws-url').value = settings.ws_url || 'ws://localhost:8000';
                    document.getElementById('reconnect-attempts').value = settings.reconnect_attempts || 5;
                    document.getElementById('reconnect-delay').value = settings.reconnect_delay || 3000;
                    document.getElementById('max-concurrent-streams').value = settings.max_concurrent_streams || 100;
                    document.getElementById('max-stream-duration').value = settings.max_stream_duration || 300;
                    document.getElementById('log-level').value = settings.log_level || 'INFO';
                    document.getElementById('theme').value = settings.theme || 'light';
                }
            });
        </script>
    </body>
    </html>
    """


# API endpoints for session management
@router.get("/api/sessions")
async def get_sessions():
    """Get user sessions."""
    # This would normally fetch from the database
    # For now, return mock data
    return {
        "sessions": [
            {
                "id": "session_123",
                "name": "Test Session",
                "created_at": "2024-01-15T10:00:00Z",
                "updated_at": "2024-01-15T10:30:00Z",
            }
        ]
    }


@router.post("/api/sessions")
async def create_session():
    """Create a new session."""
    # This would normally create a session in the database
    # For now, return mock data
    import uuid
    from datetime import datetime
    
    session_id = str(uuid.uuid4())
    return {
        "id": session_id,
        "name": f"Session {session_id[:8]}",
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }


@router.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    """Get messages for a session."""
    # This would normally fetch from the database
    # For now, return mock data
    return {
        "messages": [
            {
                "id": "msg_123",
                "role": "user",
                "content": "Hello, how are you?",
                "timestamp": "2024-01-15T10:00:00Z",
            },
            {
                "id": "msg_124",
                "role": "assistant",
                "content": "I'm doing well, thank you for asking!",
                "timestamp": "2024-01-15T10:01:00Z",
            }
        ]
    }


@router.post("/api/sessions/{session_id}/messages")
async def send_message_to_session(session_id: str, message: dict):
    """Send a message to a session."""
    # This would normally process the message and start streaming
    # For now, return mock data
    return {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": message.get("content", ""),
        "timestamp": datetime.utcnow().isoformat(),
    }


# WebSocket endpoint for real-time communication
@router.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time communication."""
    await websocket.accept()
    
    try:
        # Handle WebSocket connection
        await handle_websocket_connection(websocket, session_id, "demo_user")
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for session {session_id}")
    except Exception as e:
        logger.error(f"WebSocket error for session {session_id}: {e}")


# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        # Check WebSocket manager health
        ws_health = await websocket_manager.health_check()
        
        # Check streaming manager health
        streaming_health = await streaming_manager.health_check()
        
        # Overall health status
        overall_status = "healthy"
        issues = []
        
        if ws_health["status"] != "healthy":
            overall_status = "degraded"
            issues.extend(ws_health["issues"])
            
        if streaming_health["status"] != "healthy":
            overall_status = "degraded"
            issues.extend(streaming_health["issues"])
            
        return {
            "status": overall_status,
            "issues": issues,
            "components": {
                "websocket": ws_health,
                "streaming": streaming_health,
            },
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat(),
        }