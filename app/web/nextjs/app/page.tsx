'use client';

import { useState } from 'react';
import { ChatPage } from '@/pages/chat';
import { Session } from '@/types/session';

// Mock session data - in a real app, this would come from the API
const mockSessions: Session[] = [
  {
    id: 'session_1234567890',
    name: 'General Discussion',
    created_at: '2024-01-15T10:00:00Z',
    updated_at: '2024-01-15T10:30:00Z',
    turn_count: 5,
    status: 'active',
  },
  {
    id: 'session_0987654321',
    name: 'Code Review',
    created_at: '2024-01-14T14:00:00Z',
    updated_at: '2024-01-14T15:00:00Z',
    turn_count: 12,
    status: 'active',
  },
];

export default function Home() {
  const [currentSessionId, setCurrentSessionId] = useState('session_1234567890');
  const [sessions, setSessions] = useState<Session[]>(mockSessions);

  const handleSessionSelect = (sessionId: string) => {
    setCurrentSessionId(sessionId);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <ChatPage session_id={currentSessionId} />
    </div>
  );
}