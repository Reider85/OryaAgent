"""WebSocket provider for Next.js Web UI B-15 streaming."""

import { useEffect, useRef, useState, useCallback } from 'react';
import { WebSocketMessage, MessageType } from '../types/websocket';

interface WebSocketProviderProps {
  children: React.ReactNode;
  session_id: string;
  onConnectionChange?: (isConnected: boolean) => void;
  onMessage?: (message: WebSocketMessage) => void;
}

interface WebSocketManager {
  connect: (session_id: string) => Promise<void>;
  disconnect: () => void;
  send: (message: any) => void;
  isConnected: boolean;
  connectionId: string | null;
}

export const WebSocketProvider: React.FC<WebSocketProviderProps> = ({
  children,
  session_id,
  onConnectionChange,
  onMessage,
}) => {
  const [isConnected, setIsConnected] = useState(false);
  const [connectionId, setConnectionId] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimeout = useRef<NodeJS.Timeout | null>(null);
  
  const wsRef = useRef<WebSocket | null>(null);

  // Create WebSocket manager
  const wsManager: WebSocketManager = {
    connect: useCallback(async (session_id: string) => {
      try {
        const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'}/ws/${session_id}`;
        
        wsRef.current = new WebSocket(wsUrl);
        
        wsRef.current.onopen = () => {
          console.log('WebSocket connected');
          setIsConnected(true);
          setConnectionError(null);
          reconnectAttempts.current = 0;
          onConnectionChange?.(true);
        };
        
        wsRef.current.onmessage = (event) => {
          try {
            const message = JSON.parse(event.data);
            
            // Handle different message types
            switch (message.type) {
              case MessageType.CONNECTION:
                setConnectionId(message.connection_id);
                break;
              case MessageType.ERROR:
                setConnectionError(message.content);
                break;
            }
            
            onMessage?.(message);
          } catch (error) {
            console.error('Error parsing WebSocket message:', error);
          }
        };
        
        wsRef.current.onclose = (event) => {
          console.log('WebSocket disconnected:', event.code, event.reason);
          setIsConnected(false);
          setConnectionId(null);
          onConnectionChange?.(false);
          
          // Attempt reconnection
          if (event.code !== 1000) { // 1000 = normal closure
            handleReconnect();
          }
        };
        
        wsRef.current.onerror = (error) => {
          console.error('WebSocket error:', error);
          setConnectionError('WebSocket connection error');
          setIsConnected(false);
          onConnectionChange?.(false);
        };
        
      } catch (error) {
        console.error('Failed to connect to WebSocket:', error);
        setConnectionError('Failed to establish connection');
        setIsConnected(false);
        onConnectionChange?.(false);
      }
    }, [onConnectionChange, onMessage]),
    
    disconnect: useCallback(() => {
      if (reconnectTimeout.current) {
        clearTimeout(reconnectTimeout.current);
        reconnectTimeout.current = null;
      }
      
      if (wsRef.current) {
        wsRef.current.close(1000, 'Client disconnect');
        wsRef.current = null;
      }
      
      setIsConnected(false);
      setConnectionId(null);
      onConnectionChange?.(false);
    }, [onConnectionChange]),
    
    send: useCallback((message: any) => {
      if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify(message));
      } else {
        console.warn('WebSocket not connected, cannot send message');
      }
    }, []),
    
    isConnected: isConnected,
    connectionId: connectionId,
  };

  // Handle reconnection with exponential backoff
  const handleReconnect = useCallback(() => {
    if (reconnectAttempts.current >= 5) {
      console.log('Max reconnection attempts reached');
      setConnectionError('Connection failed after multiple attempts');
      return;
    }
    
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
    reconnectAttempts.current++;
    
    console.log(`Attempting to reconnect in ${delay}ms (attempt ${reconnectAttempts.current})`);
    
    reconnectTimeout.current = setTimeout(() => {
      wsManager.connect(session_id);
    }, delay);
  }, [session_id, wsManager]);

  // Connect on mount and session_id change
  useEffect(() => {
    wsManager.connect(session_id);
    
    return () => {
      wsManager.disconnect();
    };
  }, [session_id, wsManager]);

  // Auto-reconnect if connection is lost
  useEffect(() => {
    if (!isConnected && reconnectAttempts.current < 5) {
      handleReconnect();
    }
  }, [isConnected, handleReconnect]);

  return (
    <WebSocketContext.Provider value={wsManager}>
      {children}
    </WebSocketContext.Provider>
  );
};

// Create context
interface WebSocketContextType extends WebSocketManager {
  isConnected: boolean;
  connectionId: string | null;
  connectionError: string | null;
}

const WebSocketContext = React.createContext<WebSocketContextType | null>(null);

export const useWebSocket = (): WebSocketContextType => {
  const context = React.useContext(WebSocketContext);
  if (!context) {
    throw new Error('useWebSocket must be used within a WebSocketProvider');
  }
  return context;
};

export default WebSocketProvider;