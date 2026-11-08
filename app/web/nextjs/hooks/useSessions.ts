import { useState, useEffect, useCallback, useRef } from 'react';
import { SessionInfo, SessionFilter, SessionStatus } from '@/types/session';

interface WebSocketMessage {
  type: 'session_update' | 'session_created' | 'session_deleted';
  session?: SessionInfo;
  sessionId?: string;
}

export const useSessions = (filters?: SessionFilter) => {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    
    try {
      const response = await fetch('/web/api/sessions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(filters || {}),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      setSessions(data.sessions || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch sessions');
    } finally {
      setLoading(false);
    }
  }, [filters]);

  const createSession = useCallback(async (sessionData: { name: string; description?: string; workspace?: string }) => {
    try {
      const response = await fetch('/web/api/sessions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(sessionData),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const newSession = await response.json();
      setSessions(prev => [newSession, ...prev]);
      return newSession;
    } catch (err) {
      throw new Error(err instanceof Error ? err.message : 'Failed to create session');
    }
  }, []);

  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      const response = await fetch(`/web/api/sessions/${sessionId}`, {
        method: 'DELETE',
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      setSessions(prev => prev.filter(session => session.id !== sessionId));
      return true;
    } catch (err) {
      throw new Error(err instanceof Error ? err.message : 'Failed to delete session');
    }
  }, []);

  const updateSession = useCallback(async (sessionId: string, updates: { name?: string; description?: string; status?: SessionStatus }) => {
    try {
      const response = await fetch(`/web/api/sessions/${sessionId}`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(updates),
      });

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }

      const updatedSession = await response.json();
      setSessions(prev => prev.map(session => 
        session.id === sessionId ? updatedSession : session
      ));
      return updatedSession;
    } catch (err) {
      throw new Error(err instanceof Error ? err.message : 'Failed to update session');
    }
  }, []);

  const connectWebSocket = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    try {
      wsRef.current = new WebSocket('/ws/sessions');
      
      wsRef.current.onopen = () => {
        console.log('WebSocket connected for sessions');
      };

      wsRef.current.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          
          switch (message.type) {
            case 'session_created':
              if (message.session) {
                setSessions(prev => [message.session!, ...prev]);
              }
              break;
            case 'session_deleted':
              if (message.sessionId) {
                setSessions(prev => prev.filter(session => session.id !== message.sessionId));
              }
              break;
            case 'session_update':
              if (message.session) {
                setSessions(prev => prev.map(session => 
                  session.id === message.session?.id ? message.session! : session
                ));
              }
              break;
          }
        } catch (err) {
          console.error('Error parsing WebSocket message:', err);
        }
      };

      wsRef.current.onclose = () => {
        console.log('WebSocket disconnected for sessions');
        // Attempt to reconnect after 3 seconds
        setTimeout(connectWebSocket, 3000);
      };

      wsRef.current.onerror = (err) => {
        console.error('WebSocket error:', err);
        setError('WebSocket connection failed');
      };
    } catch (err) {
      console.error('Failed to connect WebSocket:', err);
      setError('WebSocket connection failed');
    }
  }, []);

  useEffect(() => {
    fetchSessions();
    connectWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [fetchSessions, connectWebSocket]);

  return {
    sessions,
    loading,
    error,
    fetchSessions,
    createSession,
    deleteSession,
    updateSession,
  };
};