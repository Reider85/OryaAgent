import { SessionItem } from './SessionItem';
import { SessionInfo } from '@/types/session';

interface SessionListProps {
  sessions: SessionInfo[];
  selectedId: string | null;
  onSelect: (sessionId: string) => void;
  onMenuClick?: (session: SessionInfo) => void;
}

export const SessionList = ({ 
  sessions, 
  selectedId, 
  onSelect, 
  onMenuClick 
}: SessionListProps) => {
  if (sessions.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-500">
        <div className="text-center">
          <div className="w-12 h-12 mx-auto mb-3 bg-gray-100 rounded-full flex items-center justify-center">
            <svg className="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
            </svg>
          </div>
          <p className="text-sm font-medium">No sessions found</p>
          <p className="text-xs mt-1">Create a new session to get started</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      {sessions.map((session) => (
        <SessionItem
          key={session.id}
          session={session}
          isSelected={selectedId === session.id}
          onSelect={onSelect}
          onMenuClick={onMenuClick}
        />
      ))}
    </div>
  );
};