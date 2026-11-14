"""WebSocket types for Next.js Web UI B-15 streaming."""

export enum MessageType {
  USER = 'user',
  ASSISTANT = 'assistant',
  ERROR = 'error',
  TOOL_CALL = 'tool_call',
  TOOL_RESULT = 'tool_result',
  STREAM_TOKEN = 'stream_token',
  STREAM_COMPLETE = 'stream_complete',
  CONNECTION = 'connection',
  STATUS = 'status',
}

export interface WebSocketMessage {
  id: string;
  type: MessageType;
  content: string;
  timestamp: string;
  session_id?: string;
  role?: 'user' | 'assistant' | 'system';
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

export interface UserMessage extends WebSocketMessage {
  type: MessageType.USER;
  role: 'user';
  content: string;
}

export interface AssistantMessage extends WebSocketMessage {
  type: MessageType.ASSISTANT;
  role: 'assistant';
  content: string;
  position?: number;
  total_tokens?: number;
}

export interface ErrorMessage extends WebSocketMessage {
  type: MessageType.ERROR;
  content: string;
  error_code?: string;
}

export interface ToolCallMessage extends WebSocketMessage {
  type: MessageType.TOOL_CALL;
  tool_name: string;
  tool_args: Record<string, any>;
  tool_call_id: string;
  start_time: string;
  status: string;
}

export interface ToolResultMessage extends WebSocketMessage {
  type: MessageType.TOOL_RESULT;
  tool_name: string;
  tool_call_id: string;
  result: any;
  status: string;
  end_time: string;
  duration_ms?: number;
  error_message?: string;
}

export interface StreamTokenMessage extends WebSocketMessage {
  type: MessageType.STREAM_TOKEN;
  content: string;
  position: number;
  request_id: string;
  total_tokens?: number;
}

export interface StreamCompleteMessage extends WebSocketMessage {
  type: MessageType.STREAM_COMPLETE;
  request_id: string;
  total_tokens?: number;
  duration_ms?: number;
}

export interface ConnectionMessage extends WebSocketMessage {
  type: MessageType.CONNECTION;
  message: string;
  connection_id?: string;
}

export interface StatusMessage extends WebSocketMessage {
  type: MessageType.STATUS;
  status_type: string;
  message: string;
  details?: Record<string, any>;
}

// Client message types
export interface ClientMessage {
  type: string;
  content?: string;
  session_id: string;
  request_id?: string;
  user_id?: string;
}

export interface ClientChatMessage extends ClientMessage {
  type: 'message';
  content: string;
}

export interface ClientToolCallMessage extends ClientMessage {
  type: 'tool_call';
  tool_name: string;
  arguments: Record<string, any>;
}

export interface ClientStreamRequestMessage extends ClientMessage {
  type: 'stream_request';
  prompt: string;
  streaming_mode: string;
}

// Message utilities
export const createMessage = (type: MessageType, data: Partial<WebSocketMessage>): WebSocketMessage => {
  const baseMessage: WebSocketMessage = {
    id: `${type}_${Date.now()}`,
    type,
    content: data.content || '',
    timestamp: new Date().toISOString(),
    session_id: data.session_id,
  };
  
  return { ...baseMessage, ...data };
};

export const createUserMessage = (content: string, session_id: string): UserMessage => ({
  id: `user_${Date.now()}`,
  type: MessageType.USER,
  content,
  timestamp: new Date().toISOString(),
  session_id,
  role: 'user',
});

export const createAssistantMessage = (content: string, session_id: string): AssistantMessage => ({
  id: `assistant_${Date.now()}`,
  type: MessageType.ASSISTANT,
  content,
  timestamp: new Date().toISOString(),
  session_id,
  role: 'assistant',
});

export const createErrorMessage = (content: string, session_id: string): ErrorMessage => ({
  id: `error_${Date.now()}`,
  type: MessageType.ERROR,
  content,
  timestamp: new Date().toISOString(),
  session_id,
});

export const createStreamTokenMessage = (
  token: string,
  position: number,
  session_id: string,
  request_id: string
): StreamTokenMessage => ({
  id: `token_${position}_${Date.now()}`,
  type: MessageType.STREAM_TOKEN,
  content: token,
  position,
  timestamp: new Date().toISOString(),
  session_id,
  request_id,
});

export const createStreamCompleteMessage = (
  request_id: string,
  session_id: string
): StreamCompleteMessage => ({
  id: `stream_complete_${Date.now()}`,
  type: MessageType.STREAM_COMPLETE,
  request_id,
  timestamp: new Date().toISOString(),
  session_id,
});

// WebSocket event handlers
export type WebSocketEventHandler = (message: WebSocketMessage) => void;
export type ConnectionEventHandler = (isConnected: boolean) => void;