import { useState, useEffect } from 'react';
import { SessionSidebar as SessionSidebarType } from './SessionSidebar';
import { SessionSearch } from './SessionSearch';
import { SessionFilters } from './SessionFilters';
import { SessionList } from './SessionList';
import { SessionActions } from './SessionActions';
import { useSessions } from '@/hooks/useSessions';
import { SessionStatus } from '@/types/session';

export const SessionSidebar: React.FC = () => {
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<SessionStatus[]>(['active']);
  
  const { 
    sessions, 
    loading, 
    error, 
    createSession, 
    deleteSession, 
    updateSession 
  } = useSessions({
    search: searchTerm,
    status: statusFilter,
  });

  const handleCreateSession = async () => {
    try {
      await createSession({
        name: `New Session ${sessions.length + 1}`,
        description: 'Created automatically',
      });
    } catch (err) {
      console.error('Failed to create session:', err);
    }
  };

  const handleDeleteSession = async (sessionId: string) => {
    try {
      await deleteSession(sessionId);
      if (selectedSessionId === sessionId) {
        setSelectedSessionId(null);
      }
    } catch (err) {
      console.error('Failed to delete session:', err);
    }
  };

  const handleUpdateSession = async (
    sessionId: string, 
    updates: { name?: string; description?: string; status?: SessionStatus }
  ) => {
    try {
      await updateSession(sessionId, updates);
    } catch (err) {
      console.error('Failed to update session:', err);
    }
  };

  const handleMenuClick = (session: any) => {
    // This could open a context menu or modal for more actions
    console.log('Menu clicked for session:', session);
  };

  // Auto-select first session if none selected and sessions exist
  useEffect(() => {
    if (sessions.length > 0 && !selectedSessionId) {
      setSelectedSessionId(sessions[0].id);
    }
  }, [sessions, selectedSessionId]);

  return (
    <div className="w-80 bg-white border-r border-gray-200 h-full flex flex-col">
      {/* Header */}
      <div className="p-4 border-b border-gray-200">
        <h2 className="text-lg font-semibold text-gray-900">Sessions</h2>
        <p className="text-xs text-gray-500 mt-1">
          {sessions.length} session{sessions.length !== 1 ? 's' : ''}
        </p>
        <SessionActions
          onCreateSession={handleCreateSession}
          onDeleteSession={handleDeleteSession}
          onUpdateSession={handleUpdateSession}
          selectedSession={sessions.find(s => s.id === selectedSessionId) || null}
        />
      </div>
      
      {/* Search and Filter */}
      <div className="p-4 border-b border-gray-200 space-y-3">
        <SessionSearch 
          value={searchTerm}
          onChange={setSearchTerm}
        />
        <SessionFilters
          selected={statusFilter}
          onChange={setStatusFilter}
        />
      </div>
      
      {/* Session List */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-center">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-2"></div>
              <p className="text-sm text-gray-500">Loading sessions...</p>
            </div>
          </div>
        ) : error ? (
          <div className="flex items-center justify-center h-64">
            <div className="text-center">
              <div className="w-12 h-12 mx-auto mb-3 bg-red-100 rounded-full flex items-center justify-center">
                <svg className="w-6 h-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
              </div>
              <p className="text-sm font-medium text-red-600">Error</p>
              <p className="text-xs text-gray-500 mt-1">{error}</p>
            </div>
          </div>
        ) : (
          <SessionList
            sessions={sessions}
            selectedId={selectedSessionId}
            onSelect={setSelectedSessionId}
            onMenuClick={handleMenuClick}
          />
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-gray-200 text-xs text-gray-500">
        <p>Click on a session to start chatting</p>
        <p className="mt-1">Real-time updates enabled</p>
      </div>
    </div>
  );
};