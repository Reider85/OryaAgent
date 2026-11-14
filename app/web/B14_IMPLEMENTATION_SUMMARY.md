# B-14: Next.js Web UI: Tool-Call Visualization

## Overview
This implementation adds a collapsible JSON tree visualization for tool calls in the Next.js Web UI (B-14). It provides users with an intuitive way to explore tool call execution in real-time.

## Features Implemented

### 1. Frontend Components

#### ToolCallVisualization.tsx
- **Location**: `app/web/nextjs/components/ToolCallVisualization.tsx`
- **Features**:
  - Hierarchical tree display of tool calls
  - Expandable/collapsible nodes
  - Real-time updates via WebSocket
  - Search and filter functionality
  - Statistics panel with success rates and execution times
  - Status indicators (running, completed, failed, error)
  - Formatted display of arguments, results, and errors

#### ChatInterface Integration
- **Location**: `app/web/nextjs/components/ChatInterface.tsx`
- **Features**:
  - "Show Tool Calls" button in chat interface
  - Collapsible tool call panel within chat
  - Integration with existing WebSocket system

#### Dedicated Page
- **Location**: `app/web/nextjs/app/sessions/[sessionId]/tool-calls/page.tsx`
- **Features**:
  - Full-screen tool call visualization
  - Navigation back to chat interface
  - Comprehensive tool call analysis

### 2. Backend API

#### Tool Call Visualization API
- **Location**: `app/ui/tool_visualization.py`
- **Endpoints**:
  - `GET /ui/api/sessions/{session_id}/tool-calls` - Get all tool calls
  - `GET /ui/api/sessions/{session_id}/tool-calls/tree` - Get hierarchical tree structure
  - `GET /ui/api/sessions/{session_id}/tool-calls/{tool_call_id}` - Get detailed information
  - `GET /ui/api/sessions/{session_id}/tool-calls/statistics` - Get statistics
  - `GET /ui/api/sessions/{session_id}/tool-calls/search` - Search tool calls
  - `GET /ui/api/sessions/{session_id}/tool-calls/{tool_call_id}/formatted` - Get formatted display

#### WebSocket Integration
- **Location**: `app/web/nextjs_ui.py`
- **Features**:
  - Real-time tool call updates
  - Tool call start and result messages
  - Error handling for tool execution

### 3. Type Definitions

#### Tool-Call Types
- **Location**: `app/web/nextjs/types/tool-call.ts`
- **Interfaces**:
  - `ToolCallNode` - Individual tool call with hierarchy
  - `ToolCallStats` - Statistics about tool calls
  - `ToolCallSearchResult` - Search results
  - `FormattedToolCall` - Formatted display data

## Implementation Details

### Data Structure
```typescript
interface ToolCallNode {
  id: string;
  name: string;
  arguments: Record<string, any>;
  start_time: string;
  end_time?: string;
  duration_ms?: number;
  status: 'running' | 'completed' | 'failed' | 'error';
  result?: any;
  error?: string;
  children: ToolCallNode[];
}
```

### Key Features

#### 1. Tree Visualization
- Hierarchical display of parent-child tool call relationships
- Expandable/collapsible nodes with smooth animations
- Visual indicators for different tool call statuses
- Formatted display of arguments, results, and errors

#### 2. Real-time Updates
- WebSocket integration for live tool call updates
- Tool call start notifications
- Tool call result notifications with timing information
- Error notifications for failed tool calls

#### 3. Search and Filter
- Search by tool name or arguments
- Filter by status (completed, failed, running, error)
- Real-time filtering with instant results

#### 4. Statistics
- Total number of tool calls
- Success rate calculation
- Average execution time
- Tool call frequency by type
- Status distribution

#### 5. User Experience
- Loading states with spinners
- Error handling with retry options
- Responsive design for mobile and desktop
- Intuitive navigation between chat and tool call views

## Integration Points

### 1. Chat Interface (B-11)
- "Show Tool Calls" button in chat header
- Collapsible tool call panel below chat messages
- Seamless integration with existing chat functionality

### 2. Session Sidebar (B-12)
- Tool call statistics displayed in session overview
- Quick access to tool call visualization

### 3. Settings Panel (B-13)
- Configuration options for tool call display
- User preferences for formatting and behavior

### 4. WebSocket Streaming (B-15)
- Real-time tool call updates
- Live status changes
- Error notifications

## Testing

### Unit Tests
- **Location**: `app/web/test_tool_call_visualization.py`
- **Coverage**:
  - API endpoint availability
  - Route configuration
  - Error handling

### Manual Testing
1. **Chat Integration**:
   - Start a new chat session
   - Click "Show Tool Calls" button
   - Verify tool call panel appears
   - Test expand/collapse functionality

2. **Dedicated Page**:
   - Navigate to `/sessions/[sessionId]/tool-calls`
   - Verify full-screen visualization
   - Test search and filter functionality

3. **Real-time Updates**:
   - Start a chat session
   - Send messages that trigger tool calls
   - Verify tool calls appear in real-time

## Dependencies

### Backend
- `app/ui/tool_visualization.py` - Main visualization logic
- `app/web/nextjs_ui.py` - WebSocket integration
- `app/core/session.py` - Session management

### Frontend
- `app/web/nextjs/components/ToolCallVisualization.tsx` - Main visualization component
- `app/web/nextjs/components/ChatInterface.tsx` - Chat integration
- `app/web/nextjs/types/tool-call.ts` - Type definitions

## Future Enhancements

1. **Performance Optimizations**:
   - Virtual scrolling for large trees
   - Lazy loading of child nodes
   - Debounced search

2. **Enhanced Features**:
   - Export functionality (JSON, CSV)
   - Time range filtering
   - Tool call comparison

3. **Advanced Visualization**:
   - Timeline view
   - Dependency graph view
   - Performance analytics

4. **Integration**:
   - Link to tool source code
   - Related message context
   - Error resolution suggestions

## Acceptance Criteria

### Functional Requirements
- ✅ Tool calls displayed as collapsible JSON tree
- ✅ Real-time updates via WebSocket
- ✅ Search and filter functionality
- ✅ Statistics panel with performance metrics
- ✅ Integration with chat interface
- ✅ Responsive design

### Technical Requirements
- ✅ Full TypeScript implementation
- ✅ Integration with existing backend APIs
- ✅ Proper error handling
- ✅ Performance with large trees
- ✅ Accessibility compliance
- ✅ Consistent with existing UI patterns

### User Experience
- ✅ Intuitive navigation between chat and tool call views
- ✅ Clear visual indicators for tool call status
- ✅ Easy to understand hierarchical display
- ✅ Responsive to user interactions (expand/collapse, search)