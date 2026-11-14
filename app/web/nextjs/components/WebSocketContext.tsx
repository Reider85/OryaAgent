"""WebSocket context for state management in Next.js Web UI."""

import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { WebSocketMessage, MessageType } from '../types/websocket';

interface WebSocketContextType {
  isConnected: boolean;
  connectionId: string | null;
  connectionError: string | null;
  messages: WebSocketMessage[];
  sendMessage: (message: any) => void;
  sendChatMessage: (content: string) => void;
  sendStreamRequest: (prompt: string) => void;
  clearMessages: () => void;
  connectionStatus: 'connecting' | 'connected' | 'disconnected' | 'error';
}

const WebSocketContext = createContext<WebSocketContextType | null>(null);

interface WebSocketProviderProps {
  children: React.ReactNode;
  session_id: string;
  onConnectionChange?: (isConnected: boolean) => void;
  onMessage?: (message: WebSocketMessage) => void;
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
  const [messages, setMessages] = useState<WebSocketMessage[]>([]);
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected');
  
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectAttempts = useRef(0);
  const reconnectTimeout = useRef<NodeJS.Timeout | null>(null);

  // WebSocket connection management
  const connectWebSocket = useCallback(() => {
    try {
      setConnectionStatus('connecting');
      
      const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'}/ws/${session_id}`;
      wsRef.current = new WebSocket(wsUrl);
      
      wsRef.current.onopen = () => {
        console.log('WebSocket connected');
        setIsConnected(true);
        setConnectionError(null);
        setConnectionStatus('connected');
        reconnectAttempts.current = 0;
        onConnectionChange?.(true);
      };
      
      wsRef.current.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data);
          
          // Update connection state
          if (message.type === MessageType.CONNECTION) {
            setConnectionId(message.connection_id);
          }
          
          if (message.type === MessageType.ERROR) {
            setConnectionError(message.content);
            setConnectionStatus('error');
          }
          
          // Add to messages
          setMessages(prev => [...prev, message]);
          onMessage?.(message);
          
        } catch (error) {
          console.error('Error parsing WebSocket message:', error);
        }
      };
      
      wsRef.current.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason);
        setIsConnected(false);
        setConnectionId(null);
        setConnectionStatus('disconnected');
        onConnectionChange?.(false);
        
        // Attempt reconnection if not normal closure
        if (event.code !== 1000) {
          handleReconnect();
        }
      };
      
      wsRef.current.onerror = (error) => {
        console.error('WebSocket error:', error);
        setConnectionError('WebSocket connection error');
        setConnectionStatus('error');
        setIsConnected(false);
        onConnectionChange?.(false);
      };
      
    } catch (error) {
      console.error('Failed to connect to WebSocket:', error);
      setConnectionError('Failed to establish connection');
      setConnectionStatus('error');
      setIsConnected(false);
      onConnectionChange?.(false);
    }
  }, [session_id, onConnectionChange, onMessage]);

  // Handle reconnection with exponential backoff
  const handleReconnect = useCallback(() => {
    if (reconnectAttempts.current >= 5) {
      console.log('Max reconnection attempts reached');
      setConnectionError('Connection failed after multiple attempts');
      setConnectionStatus('error');
      return;
    }
    
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.current), 30000);
    reconnectAttempts.current++;
    
    console.log(`Attempting to reconnect in ${delay}ms (attempt ${reconnectAttempts.current})`);
    
    reconnectTimeout.current = setTimeout(() => {
      connectWebSocket();
    }, delay);
  }, [connectWebSocket]);

  // Disconnect WebSocket
  const disconnectWebSocket = useCallback(() => {
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
    setConnectionStatus('disconnected');
    onConnectionChange?.(false);
  }, [onConnectionChange]);

  // Send message to WebSocket
  const sendMessage = useCallback((message: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message));
    } else {
      console.warn('WebSocket not connected, cannot send message');
    }
  }, []);

  // Send chat message
  const sendChatMessage = useCallback((content: string) => {
    sendMessage({
      type: 'message',
      content,
      session_id,
      user_id: 'default_user',
    });
  }, [sendMessage, session_id]);

  // Send stream request
  const sendStreamRequest = useCallback((prompt: string) => {
    sendMessage({
      type: 'stream_request',
      prompt,
      session_id,
      user_id: 'default_user',
      streaming_mode: 'tokens',
    });
  }, [sendMessage, session_id]);

  // Clear messages
  const clearMessages = useCallback(() => {
    setMessages([]);
  }, []);

  // Connect on mount and cleanup on unmount
  useEffect(() => {
    connectWebSocket();
    
    return () => {
      disconnectWebSocket();
    };
  }, [connectWebSocket, disconnectWebSocket]);

  // Auto-reconnect if connection is lost
  useEffect(() => {
    if (!isConnected && connectionStatus === 'disconnected' && reconnectAttempts.current < 5) {
      handleReconnect();
    }
  }, [isConnected, connectionStatus, handleReconnect]);

  const contextValue: WebSocketContextType = {
    isConnected,
    connectionId,
    connectionError,
    messages,
    sendMessage,
    sendChatMessage,
    sendStreamRequest,
    clearMessages,
    connectionStatus,
  };

  return (
    <WebSocketContext.Provider value={contextValue}>
      {children}
    </WebSocketContext.Provider>
  );
};

export const useWebSocket = (): WebSocketContextType => {
  const context = useContext(WebSocketContext);
  if (!context) {
    throw new Error('useWebSocket must be used within a WebSocketProvider');
  }
  return context;
};

export default WebSocketProvider;