# Next.js Web UI (B-11) Implementation

This directory contains the Next.js Web UI implementation for OryaAgent (B-11 ticket).

## Overview

The Next.js Web UI provides a modern, responsive chat interface that runs parallel to Chainlit. It includes:

- **Real-time chat interface** with WebSocket streaming
- **Session management** (create, list, view)
- **Tool call visualization** 
- **Authentication integration**
- **Soft limit handling** (no error indicators for recursion limits)

## File Structure

```
app/web/
├── nextjs_ui.py              # FastAPI routes and WebSocket handlers
├── nextjs/                   # Next.js application
│   ├── package.json          # Dependencies
│   ├── tsconfig.json         # TypeScript config
│   ├── next.config.js        # Next.js config
│   ├── tailwind.config.js    # Tailwind CSS config
│   ├── postcss.config.js     # PostCSS config
│   ├── styles/
│   │   └── globals.css       # Global styles
│   ├── app/
│   │   ├── layout.tsx        # Root layout
│   │   └── page.tsx          # Main chat page
│   ├── components/
│   │   ├── ChatInterface.tsx # Main chat component
│   │   ├── WebSocketProvider.tsx # WebSocket management
│   │   └── WebSocketContext.tsx # React context for WebSocket
│   └── lib/                  # Utility functions
├── templates/
│   └── nextjs/
│       └── chat.html         # Fallback HTML template
├── dev_nextjs.py             # Development script
└── test_nextjs_ui.py         # Test script
```

## Features

### 1. Real-time Chat Interface
- WebSocket-based real-time communication
- Message streaming with token-by-token updates
- Tool call execution visualization
- Error handling with soft limit support

### 2. Session Management
- Create new sessions
- List existing sessions
- Session-specific message history
- User authentication integration

### 3. Tool Call Visualization
- Real-time tool execution status
- Tool arguments and results display
- Error handling for tool failures

### 4. Soft Limit Handling
- No error indicators for recursion/step limits
- Natural completion messages for soft limits
- Audit logging for limit triggers

## Implementation Details

### Backend (FastAPI)

The backend is implemented in `nextjs_ui.py` and provides:

- **WebSocket endpoint** (`/ws/{session_id}`) for real-time communication
- **REST API endpoints** for session and message management
- **Agent integration** with LangGraph for message processing
- **Authentication** using existing OryaAuth system
- **Soft limit handling** with graceful degradation

### Frontend (Next.js)

The frontend is a React/TypeScript application with:

- **Modern UI** using Tailwind CSS
- **WebSocket client** for real-time communication
- **Responsive design** for mobile and desktop
- **TypeScript** for type safety
- **Component architecture** for maintainability

## API Endpoints

### WebSocket Endpoints

- `ws://localhost:8000/ws/{session_id}` - Real-time chat communication

### REST API Endpoints

- `GET /web/` - Chat interface UI
- `GET /web/sessions` - Sessions sidebar UI
- `GET /web/settings` - Settings panel UI
- `GET /web/api/sessions` - List user sessions
- `POST /web/api/sessions` - Create new session
- `GET /web/api/sessions/{id}/messages` - Get session messages
- `POST /web/api/sessions/{id}/messages` - Send message to session

## Message Types

### WebSocket Messages

```typescript
interface Message {
  type: 'user' | 'assistant' | 'error' | 'tool_call' | 'tool_result' | 'stream_token' | 'connection';
  content: string;
  timestamp: string;
  role?: 'user' | 'assistant' | 'system';
  session_id?: string;
  tool_name?: string;
  tool_args?: any;
  tool_result?: any;
  request_id?: string;
  position?: number;
  total_tokens?: number;
}
```

### Client to Server Messages

```typescript
{
  type: 'message' | 'tool_call' | 'stream_request';
  content: string; // for message type
  tool_name: string; // for tool_call type
  arguments: any; // for tool_call type
  prompt: string; // for stream_request type
  session_id: string;
}
```

### Server to Client Messages

```typescript
{
  type: 'message' | 'tool_call' | 'tool_result' | 'stream_token' | 'stream_complete' | 'error';
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  session_id: string;
  tool_name?: string;
  tool_args?: any;
  tool_result?: any;
  request_id?: string;
  position?: number;
  total_tokens?: number;
}
```

## Development

### Running the Development Server

1. **Start the OryaAgent backend:**
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```

2. **Start the Next.js development server:**
   ```bash
   cd app/web/nextjs
   npm install
   npm run dev
   ```

3. **Access the interface:**
   - Chat interface: http://localhost:3000
   - API endpoints: http://localhost:8000/web/

### Testing

Run the test script to verify the implementation:

```bash
python app/web/test_nextjs_ui.py
```

## Integration with OryaAgent

### Agent Integration

The Next.js UI integrates with the OryaAgent system through:

1. **Graph Integration**: Uses the existing LangGraph for message processing
2. **Tool Integration**: Supports all existing tools (read, write, edit, bash, grep, glob)
3. **Memory Integration**: Uses existing memory system for session persistence
4. **Authentication**: Uses existing auth system for user management

### Soft Limit Handling

The implementation follows the BETA phase requirements:

- **No error indicators** for soft limits (recursion/step limits)
- **Natural completion messages** for limit triggers
- **Audit logging** for limit events
- **Graceful degradation** for hard errors only

## Configuration

### Environment Variables

- `NEXT_PUBLIC_API_URL`: Backend API URL (default: http://localhost:8000)
- `ORYA_ENV`: Environment mode (dev/prod)

### Backend Configuration

The backend uses existing OryaAgent configuration:

- Authentication: `get_current_user` dependency
- Security: Existing security middleware
- Observability: Existing span emission system

## Future Enhancements

1. **B-12**: Sessions sidebar with search and filtering
2. **B-13**: Settings panel for LLM provider configuration
3. **B-14**: Tool call visualization with JSON tree
4. **B-15**: WebSocket streaming optimizations
5. **Production deployment**: Docker configuration and CI/CD

## Troubleshooting

### Common Issues

1. **WebSocket connection fails**: Check if backend is running on port 8000
2. **Module not found errors**: Run `npm install` in the nextjs directory
3. **CORS issues**: Ensure backend CORS is configured correctly
4. **Authentication errors**: Verify user authentication system is working

### Debug Mode

Enable debug logging:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

## Contributing

When contributing to this implementation:

1. Follow the existing code style and patterns
2. Ensure TypeScript for all frontend code
3. Add appropriate error handling
4. Test both WebSocket and REST API endpoints
5. Follow soft limit handling requirements

## License

This implementation is part of the OryaAgent project and follows the same license terms.