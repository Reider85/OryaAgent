export interface Session {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  turn_count: number;
  status: 'active' | 'inactive' | 'archived';
}

export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp: string;
  type: 'text' | 'tool_call' | 'tool_result';
  tool_name?: string;
  tool_args?: Record<string, any>;
  tool_result?: any;
}

export interface WebSocketMessage {
  id: string;
  type: string;
  content: string;
  timestamp: string;
  session_id?: string;
  role?: string;
  request_id?: string;
  position?: number;
  total_tokens?: number;
  tool_name?: string;
  tool_args?: Record<string, any>;
  tool_call_id?: string;
  result?: any;
  status?: string;
  start_time?: string;
  end_time?: string;
  duration_ms?: number;
  error_message?: string;
  connection_id?: string;
  message?: string;
  status_type?: string;
  details?: Record<string, any>;
}

export interface Settings {
  llm_provider: string;
  llm_model: string;
  max_tokens: number;
  temperature: number;
  stream_enabled: boolean;
  auto_save: boolean;
  theme: 'light' | 'dark';
  notifications: boolean;
}

export interface WebSocketContextType {
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