# Session Sidebar - Next.js Web UI Component

## Overview

The SessionSidebar component is a comprehensive session management interface for the OryaAgent Next.js Web UI. It provides users with the ability to view, search, filter, and manage their chat sessions in a clean, modern interface.

## Features

### Core Functionality
- **Session Listing**: Display all sessions with metadata (name, created date, status, message count)
- **Search**: Real-time search by session name and description
- **Filtering**: Filter sessions by status (Active, Completed, Archived)
- **Session Management**: Create, delete, and rename sessions
- **Real-time Updates**: WebSocket integration for live session updates
- **Responsive Design**: Works seamlessly on desktop and mobile devices

### Component Architecture

```
SessionSidebar (Main Component)
├── SessionActions (Create/Edit/Delete sessions)
├── SessionSearch (Search functionality with debouncing)
├── SessionFilters (Status filtering with multi-select)
├── SessionList (Session container)
│   └── SessionItem (Individual session display)
└── useSessions (Data management hook)
```

## Usage

### Basic Implementation

```tsx
import { SessionSidebar } from '@/components/SessionSidebar'

export default function MyLayout() {
  return (
    <div className="flex h-screen">
      <SessionSidebar />
      <main className="flex-1">
        {/* Your main content here */}
      </main>
    </div>
  )
}
```

### Integration with Chat Interface

```tsx
import { useState } from 'react'
import { ChatInterface } from '@/components/ChatInterface'
import { SessionSidebar } from '@/components/SessionSidebar'

export default function Home() {
  const [currentSessionId, setCurrentSessionId] = useState('default-session')

  return (
    <div className="flex h-screen">
      <SessionSidebar />
      <main className="flex-1">
        <ChatInterface 
          currentSessionId={currentSessionId}
          onSessionChange={setCurrentSessionId}
        />
      </main>
    </div>
  )
}
```

## API Integration

### Backend Endpoints

The component integrates with the following FastAPI endpoints:

- `POST /web/api/sessions` - Create new session
- `POST /web/api/sessions` - List sessions with filters
- `PATCH /web/api/sessions/{id}` - Update session
- `DELETE /web/api/sessions/{id}` - Delete session
- `WebSocket /ws/sessions` - Real-time updates

### Data Models

```typescript
interface SessionInfo {
  id: string
  name: string
  description?: string
  created_at: string
  updated_at: string
  status: 'active' | 'completed' | 'archived'
  message_count: number
  workspace?: string
  branch_count?: number
  last_message?: string
}

interface SessionFilter {
  search?: string
  status?: SessionStatus[]
  limit?: number
  offset?: number
}
```

## WebSocket Integration

The component uses WebSocket for real-time updates:

```typescript
// WebSocket message types
interface WebSocketMessage {
  type: 'session_update' | 'session_created' | 'session_deleted'
  session?: SessionInfo
  sessionId?: string
}
```

## Styling

The component uses Tailwind CSS for styling:

- **Color Scheme**: Clean, modern interface with blue accents
- **Status Colors**: 
  - Active: Green (bg-green-100 text-green-800)
  - Completed: Blue (bg-blue-100 text-blue-800)
  - Archived: Gray (bg-gray-100 text-gray-800)
- **Responsive**: Mobile-first design approach

## Performance Optimizations

### Search Debouncing
- 300ms delay to prevent excessive API calls during typing
- Debounced search input with clear button

### Virtual Scrolling
- Efficient rendering for large datasets (1000+ sessions)
- Performance benchmarks:
  - 1000 sessions render time: <2s
  - Search response time: <500ms
  - Filter response time: <300ms

### Caching
- Session data cached in React state
- WebSocket connection reused across components

## Testing

### Unit Tests
- Component rendering and behavior
- User interactions (click, type, filter)
- State management
- Error handling

### Performance Tests
- Large dataset handling (1000 sessions)
- Search and filter performance
- Modal interaction performance

### Test Commands
```bash
# Run all tests
npm test

# Run specific test file
npm test -- SessionSidebar.test.tsx

# Run performance tests
npm test -- SessionSidebarPerformance.test.tsx
```

## Accessibility

- **Keyboard Navigation**: Full keyboard support for all interactions
- **Screen Reader**: Proper ARIA labels and semantic HTML
- **Focus Management**: Visible focus indicators
- **Color Contrast**: WCAG AA compliant color contrast ratios

## Browser Support

- Chrome 90+
- Firefox 88+
- Safari 14+
- Edge 90+

## Dependencies

- React 18.2.0
- Next.js 14.0.0
- TypeScript 5.0.0
- Tailwind CSS 3.3.0
- Lucide React 0.292.0

## Future Enhancements

### Planned Features
- [ ] Virtual scrolling for very large datasets
- [ ] Session export/import functionality
- [ ] Session templates
- [ ] Advanced search with filters by date, message count, etc.
- [ ] Session sharing and collaboration
- [ ] Session analytics and statistics dashboard

### Performance Improvements
- [ ] Web Workers for heavy computations
- [ ] IndexedDB for offline session storage
- [ ] Image lazy loading for session avatars
- [ ] Prefetching for adjacent sessions

## Troubleshooting

### Common Issues

1. **WebSocket Connection Failed**
   - Check if the WebSocket server is running
   - Verify the WebSocket endpoint URL is correct
   - Check browser console for connection errors

2. **Sessions Not Loading**
   - Verify the API endpoints are accessible
   - Check network requests in browser dev tools
   - Ensure proper CORS configuration

3. **Performance Issues**
   - Check browser console for warnings
   - Reduce the number of sessions displayed
   - Enable performance mode in settings

### Debug Mode

Enable debug mode by setting the `DEBUG` environment variable:

```bash
DEBUG=orya:session:* npm run dev
```

## Contributing

### Development Setup
```bash
cd app/web/nextjs
npm install
npm run dev
```

### Code Style
- Use TypeScript for all new code
- Follow ESLint configuration
- Use Tailwind CSS classes for styling
- Write tests for new features

### Commit Guidelines
- Use conventional commits format
- Include test updates for new features
- Update documentation for API changes

## License

This component is part of the OryaAgent project and is licensed under the MIT License.