"""Enhanced chat interface with WebSocket streaming for B-15."""

import React, { useState, useRef, useEffect, useCallback } from 'react';
import { useWebSocket } from './WebSocketContext';
import { WebSocketMessage, MessageType } from '../types/websocket';
import { Send, Bot, User, AlertCircle, Loader2 } from 'lucide-react';

interface ChatMessage {
  id: string;
  type: MessageType;
  content: string;
  timestamp: string;
  role?: 'user' | 'assistant' | 'system';
  position?: number;
  total_tokens?: number;
  tool_name?: string;
  tool_result?: any;
  status?: string;
}

interface ChatInterfaceProps {
  session_id: string;
  className?: string;
}

export const ChatInterface: React.FC<ChatInterfaceProps> = ({
  session_id,
  className = '',
}) => {
  const { 
    isConnected, 
    connectionError, 
    messages, 
    sendChatMessage, 
    sendStreamRequest,
    connectionStatus 
  } = useWebSocket();
  
  const [inputValue, setInputValue] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom
  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, scrollToBottom]);

  // Handle incoming messages
  useEffect(() => {
    const lastMessage = messages[messages.length - 1];
    
    if (lastMessage) {
      switch (lastMessage.type) {
        case MessageType.USER:
          // User message - no special handling needed
          break;
          
        case MessageType.ASSISTANT:
          // Assistant message - could add typing indicators
          setIsTyping(false);
          break;
          
        case MessageType.STREAM_TOKEN:
          // Streaming token - update the last assistant message
          setIsTyping(true);
          break;
          
        case MessageType.STREAM_COMPLETE:
          // Stream completed
          setIsTyping(false);
          break;
          
        case MessageType.TOOL_CALL:
          // Tool call started
          setIsTyping(true);
          break;
          
        case MessageType.TOOL_RESULT:
          // Tool result received
          setIsTyping(false);
          break;
          
        case MessageType.ERROR:
          // Error message
          setIsTyping(false);
          break;
      }
    }
  }, [messages]);

  // Handle form submission
  const handleSubmit = useCallback((e: React.FormEvent) => {
    e.preventDefault();
    
    if (!inputValue.trim() || !isConnected) return;
    
    const message = inputValue.trim();
    setInputValue('');
    
    // Send the message
    sendChatMessage(message);
    
    // Set typing indicator
    setIsTyping(true);
  }, [inputValue, isConnected, sendChatMessage]);

  // Handle streaming request
  const handleStreamRequest = useCallback(() => {
    if (!inputValue.trim() || !isConnected) return;
    
    const prompt = inputValue.trim();
    setInputValue('');
    
    // Send stream request
    sendStreamRequest(prompt);
    
    // Set typing indicator
    setIsTyping(true);
  }, [inputValue, isConnected, sendStreamRequest]);

  // Format timestamp
  const formatTimestamp = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  // Render message based on type
  const renderMessage = (message: ChatMessage) => {
    const isUser = message.type === MessageType.USER;
    const isAssistant = message.type === MessageType.ASSISTANT;
    const isError = message.type === MessageType.ERROR;
    const isToolCall = message.type === MessageType.TOOL_CALL;
    const isToolResult = message.type === MessageType.TOOL_RESULT;
    const isStreamToken = message.type === MessageType.STREAM_TOKEN;

    return (
      <div
        key={message.id}
        className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}
      >
        <div
          className={`max-w-[80%] rounded-lg px-4 py-3 ${
            isUser
              ? 'bg-blue-600 text-white'
              : isError
              ? 'bg-red-100 text-red-800'
              : isToolCall
              ? 'bg-purple-100 text-purple-800'
              : isToolResult
              ? 'bg-green-100 text-green-800'
              : 'bg-gray-100 text-gray-800'
          }`}
        >
          {/* Message header */}
          <div className="flex items-center gap-2 mb-2">
            {isUser ? (
              <User className="w-4 h-4" />
            ) : isError ? (
              <AlertCircle className="w-4 h-4" />
            ) : (
              <Bot className="w-4 h-4" />
            )}
            <span className="text-xs font-medium opacity-75">
              {isUser ? 'You' : isError ? 'Error' : 'Assistant'}
            </span>
            <span className="text-xs opacity-50">
              {formatTimestamp(message.timestamp)}
            </span>
          </div>

          {/* Message content */}
          {isToolCall ? (
            <div className="text-sm">
              <div className="font-medium mb-1">
                Executing: {message.tool_name}
              </div>
              <div className="text-xs opacity-75">
                {JSON.stringify(message.tool_args, null, 2)}
              </div>
            </div>
          ) : isToolResult ? (
            <div className="text-sm">
              <div className="font-medium mb-1">
                {message.tool_name} Result:
              </div>
              <div className="text-xs opacity-75">
                {typeof message.tool_result === 'string'
                  ? message.tool_result
                  : JSON.stringify(message.tool_result, null, 2)}
              </div>
              {message.status === 'error' && (
                <div className="text-red-600 text-xs mt-1">
                  Error: {message.error_message}
                </div>
              )}
            </div>
          ) : (
            <div className="text-sm whitespace-pre-wrap">
              {message.content}
            </div>
          )}

          {/* Stream progress */}
          {message.position && message.total_tokens && (
            <div className="mt-2">
              <div className="w-full bg-gray-200 rounded-full h-1">
                <div
                  className="bg-blue-600 h-1 rounded-full transition-all duration-300"
                  style={{
                    width: `${(message.position / message.total_tokens) * 100}%`,
                  }}
                />
              </div>
              <div className="text-xs opacity-50 mt-1">
                {message.position}/{message.total_tokens} tokens
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className={`flex flex-col h-full ${className}`}>
      {/* Connection status */}
      <div className="flex items-center gap-2 p-3 border-b">
        <div
          className={`w-2 h-2 rounded-full ${
            connectionStatus === 'connected'
              ? 'bg-green-500'
              : connectionStatus === 'connecting'
              ? 'bg-yellow-500'
              : connectionStatus === 'error'
              ? 'bg-red-500'
              : 'bg-gray-500'
          }`}
        />
        <span className="text-sm">
          {connectionStatus === 'connected' && 'Connected'}
          {connectionStatus === 'connecting' && 'Connecting...'}
          {connectionStatus === 'disconnected' && 'Disconnected'}
          {connectionStatus === 'error' && 'Connection Error'}
        </span>
        
        {connectionError && (
          <div className="flex items-center gap-1 text-red-600 text-sm">
            <AlertCircle className="w-4 h-4" />
            <span>{connectionError}</span>
          </div>
        )}
      </div>

      {/* Messages area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message) => (
          <ChatMessageComponent key={message.id} message={message} />
        ))}
        
        {/* Typing indicator */}
        {isTyping && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-lg px-4 py-3">
              <div className="flex items-center gap-2">
                <Loader2 className="w-4 h-4 animate-spin" />
                <span className="text-sm text-gray-600">Assistant is typing...</span>
              </div>
            </div>
          </div>
        )}
        
        <div ref={messagesEndRef} />
      </div>

      {/* Input area */}
      <div className="border-t p-4">
        <form onSubmit={handleSubmit} className="flex gap-2">
          <textarea
            ref={inputRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            placeholder="Type your message..."
            className="flex-1 resize-none border rounded-lg px-4 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
            rows={2}
            disabled={!isConnected || connectionStatus === 'error'}
          />
          <button
            type="submit"
            disabled={!isConnected || !inputValue.trim() || connectionStatus === 'error'}
            className="bg-blue-600 text-white rounded-lg px-4 py-2 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <Send className="w-4 h-4" />
            <span>Send</span>
          </button>
        </form>
        
        {/* Streaming mode toggle */}
        <div className="mt-2 flex items-center gap-4">
          <button
            onClick={handleStreamRequest}
            disabled={!isConnected || !inputValue.trim() || connectionStatus === 'error'}
            className="text-sm text-blue-600 hover:text-blue-800 disabled:text-gray-400 disabled:cursor-not-allowed"
          >
            Stream Response
          </button>
        </div>
      </div>
    </div>
  );
};

// Separate message component for better performance
const ChatMessageComponent: React.FC<{ message: WebSocketMessage }> = ({ message }) => {
  const isUser = message.type === MessageType.USER;
  const isAssistant = message.type === MessageType.ASSISTANT;
  const isError = message.type === MessageType.ERROR;
  const isToolCall = message.type === MessageType.TOOL_CALL;
  const isToolResult = message.type === MessageType.TOOL_RESULT;
  const isStreamToken = message.type === MessageType.STREAM_TOKEN;

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      <div
        className={`max-w-[80%] rounded-lg px-4 py-3 ${
          isUser
            ? 'bg-blue-600 text-white'
            : isError
            ? 'bg-red-100 text-red-800'
            : isToolCall
            ? 'bg-purple-100 text-purple-800'
            : isToolResult
            ? 'bg-green-100 text-green-800'
            : 'bg-gray-100 text-gray-800'
        }`}
      >
        {/* Message header */}
        <div className="flex items-center gap-2 mb-2">
          {isUser ? (
            <User className="w-4 h-4" />
          ) : isError ? (
            <AlertCircle className="w-4 h-4" />
          ) : (
            <Bot className="w-4 h-4" />
          )}
          <span className="text-xs font-medium opacity-75">
            {isUser ? 'You' : isError ? 'Error' : 'Assistant'}
          </span>
          <span className="text-xs opacity-50">
            {new Date(message.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
          </span>
        </div>

        {/* Message content */}
        {isToolCall ? (
          <div className="text-sm">
            <div className="font-medium mb-1">
              Executing: {message.tool_name}
            </div>
            <div className="text-xs opacity-75">
              {JSON.stringify(message.tool_args || {}, null, 2)}
            </div>
          </div>
        ) : isToolResult ? (
          <div className="text-sm">
            <div className="font-medium mb-1">
              {message.tool_name} Result:
            </div>
            <div className="text-xs opacity-75">
              {typeof message.result === 'string'
                ? message.result
                : JSON.stringify(message.result, null, 2)}
            </div>
            {message.status === 'error' && (
              <div className="text-red-600 text-xs mt-1">
                Error: {message.error_message}
              </div>
            )}
          </div>
        ) : (
          <div className="text-sm whitespace-pre-wrap">
            {message.content}
          </div>
        )}

        {/* Stream progress */}
        {message.position && message.total_tokens && (
          <div className="mt-2">
            <div className="w-full bg-gray-200 rounded-full h-1">
              <div
                className="bg-blue-600 h-1 rounded-full transition-all duration-300"
                style={{
                  width: `${(message.position / message.total_tokens) * 100}%`,
                }}
              />
            </div>
            <div className="text-xs opacity-50 mt-1">
              {message.position}/{message.total_tokens} tokens
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatInterface;