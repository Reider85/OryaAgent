"""Tool call visualization component for Next.js Web UI."""

import React, { useState, useEffect } from 'react';
import { useWebSocket } from '../components/WebSocketContext';
import { WebSocketMessage, MessageType } from '../types/websocket';
import { Play, Pause, RotateCcw, Download, Filter, Search } from 'lucide-react';

interface ToolCall {
  id: string;
  tool_name: string;
  tool_args: Record<string, any>;
  start_time: string;
  end_time?: string;
  duration_ms?: number;
  status: 'running' | 'completed' | 'error';
  result?: any;
  error_message?: string;
}

interface ToolCallVisualizationProps {
  session_id: string;
}

export const ToolCallVisualization: React.FC<ToolCallVisualizationProps> = ({
  session_id,
}) => {
  const { isConnected, messages } = useWebSocket();
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [filteredToolCalls, setFilteredToolCalls] = useState<ToolCall[]>([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'running' | 'completed' | 'error'>('all');
  const [selectedTool, setSelectedTool] = useState<string | null>(null);

  // Extract tool calls from messages
  useEffect(() => {
    const extractedToolCalls: ToolCall[] = [];
    
    messages.forEach((message) => {
      if (message.type === MessageType.TOOL_CALL) {
        extractedToolCalls.push({
          id: message.tool_call_id || `tool_${Date.now()}`,
          tool_name: message.tool_name,
          tool_args: message.tool_args || {},
          start_time: message.start_time || new Date().toISOString(),
          status: 'running',
        });
      }
      
      if (message.type === MessageType.TOOL_RESULT) {
        const toolCall = extractedToolCalls.find(
          tc => tc.id === message.tool_call_id
        );
        if (toolCall) {
          toolCall.end_time = message.end_time || new Date().toISOString();
          toolCall.duration_ms = message.duration_ms;
          toolCall.status = message.status as 'running' | 'completed' | 'error';
          toolCall.result = message.result;
          toolCall.error_message = message.error_message;
        }
      }
    });
    
    setToolCalls(extractedToolCalls);
  }, [messages]);

  // Apply filters
  useEffect(() => {
    let filtered = toolCalls;
    
    // Apply status filter
    if (statusFilter !== 'all') {
      filtered = filtered.filter(tc => tc.status === statusFilter);
    }
    
    // Apply search filter
    if (searchQuery) {
      filtered = filtered.filter(tc =>
        tc.tool_name.toLowerCase().includes(searchQuery.toLowerCase())
      );
    }
    
    setFilteredToolCalls(filtered);
  }, [toolCalls, statusFilter, searchQuery]);

  const formatDuration = (ms?: number) => {
    if (!ms) return '-';
    return `${ms}ms`;
  };

  const formatTime = (dateString: string) => {
    const date = new Date(dateString);
    return date.toLocaleTimeString();
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'running':
        return 'bg-blue-100 text-blue-800';
      case 'completed':
        return 'bg-green-100 text-green-800';
      case 'error':
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };

  const exportToolCalls = () => {
    const dataStr = JSON.stringify(filteredToolCalls, null, 2);
    const dataBlob = new Blob([dataStr], { type: 'application/json' });
    const url = URL.createObjectURL(dataBlob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `tool_calls_${session_id}_${new Date().toISOString().split('T')[0]}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-6 border-b">
        <h2 className="text-xl font-bold text-gray-900">Tool Call Visualization</h2>
        <p className="text-sm text-gray-600 mt-1">
          Real-time tool execution tracking for session {session_id}
        </p>
      </div>

      {/* Filters and actions */}
      <div className="p-4 border-b">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-4">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search tools..."
                className="pl-10 pr-4 py-2 border rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
            
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as any)}
              className="border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">All Status</option>
              <option value="running">Running</option>
              <option value="completed">Completed</option>
              <option value="error">Error</option>
            </select>
          </div>
          
          <button
            onClick={exportToolCalls}
            disabled={!isConnected || filteredToolCalls.length === 0}
            className="bg-blue-600 text-white rounded-lg px-4 py-2 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2"
          >
            <Download className="w-4 h-4" />
            <span>Export</span>
          </button>
        </div>

        {/* Statistics */}
        <div className="grid grid-cols-4 gap-4 text-center">
          <div className="bg-gray-50 rounded-lg p-3">
            <div className="text-2xl font-bold text-gray-900">{toolCalls.length}</div>
            <div className="text-sm text-gray-600">Total Calls</div>
          </div>
          <div className="bg-blue-50 rounded-lg p-3">
            <div className="text-2xl font-bold text-blue-600">
              {toolCalls.filter(tc => tc.status === 'running').length}
            </div>
            <div className="text-sm text-blue-600">Running</div>
          </div>
          <div className="bg-green-50 rounded-lg p-3">
            <div className="text-2xl font-bold text-green-600">
              {toolCalls.filter(tc => tc.status === 'completed').length}
            </div>
            <div className="text-sm text-green-600">Completed</div>
          </div>
          <div className="bg-red-50 rounded-lg p-3">
            <div className="text-2xl font-bold text-red-600">
              {toolCalls.filter(tc => tc.status === 'error').length}
            </div>
            <div className="text-sm text-red-600">Errors</div>
          </div>
        </div>
      </div>

      {/* Tool calls list */}
      <div className="flex-1 overflow-y-auto">
        {filteredToolCalls.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-gray-500 text-center">
              <p>No tool calls found</p>
              <p className="text-sm mt-2">Start a conversation to see tool execution</p>
            </div>
          </div>
        ) : (
          <div className="p-4 space-y-3">
            {filteredToolCalls.map((toolCall) => (
              <div
                key={toolCall.id}
                className={`border rounded-lg p-4 ${
                  selectedTool === toolCall.id
                    ? 'border-blue-300 bg-blue-50'
                    : 'border-gray-200'
                }`}
                onClick={() => setSelectedTool(
                  selectedTool === toolCall.id ? null : toolCall.id
                )}
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className={`px-2 py-1 rounded-full text-xs ${getStatusColor(toolCall.status)}`}>
                      {toolCall.status}
                    </div>
                    <span className="font-medium text-gray-900">
                      {toolCall.tool_name}
                    </span>
                  </div>
                  
                  <div className="text-sm text-gray-500">
                    {formatTime(toolCall.start_time)}
                    {toolCall.end_time && (
                      <span> - {formatTime(toolCall.end_time)}</span>
                    )}
                  </div>
                </div>

                {/* Arguments */}
                <div className="mb-3">
                  <div className="text-xs font-medium text-gray-700 mb-1">Arguments:</div>
                  <div className="bg-gray-50 rounded p-2 text-xs">
                    <pre className="whitespace-pre-wrap">
                      {JSON.stringify(toolCall.tool_args, null, 2)}
                    </pre>
                  </div>
                </div>

                {/* Result */}
                {toolCall.result && (
                  <div className="mb-3">
                    <div className="text-xs font-medium text-gray-700 mb-1">Result:</div>
                    <div className="bg-gray-50 rounded p-2 text-xs">
                      <pre className="whitespace-pre-wrap">
                        {typeof toolCall.result === 'string'
                          ? toolCall.result
                          : JSON.stringify(toolCall.result, null, 2)}
                      </pre>
                    </div>
                  </div>
                )}

                {/* Error */}
                {toolCall.error_message && (
                  <div className="mb-3">
                    <div className="text-xs font-medium text-red-700 mb-1">Error:</div>
                    <div className="bg-red-50 rounded p-2 text-xs text-red-800">
                      {toolCall.error_message}
                    </div>
                  </div>
                )}

                {/* Duration */}
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span>Duration: {formatDuration(toolCall.duration_ms)}</span>
                  <span>ID: {toolCall.id}</span>
                </div>

                {/* Expanded details */}
                {selectedTool === toolCall.id && (
                  <div className="mt-4 pt-4 border-t border-gray-200">
                    <div className="grid grid-cols-2 gap-4 text-sm">
                      <div>
                        <div className="font-medium text-gray-700">Start Time:</div>
                        <div className="text-gray-600">{toolCall.start_time}</div>
                      </div>
                      <div>
                        <div className="font-medium text-gray-700">End Time:</div>
                        <div className="text-gray-600">{toolCall.end_time || 'N/A'}</div>
                      </div>
                      <div>
                        <div className="font-medium text-gray-700">Duration:</div>
                        <div className="text-gray-600">{formatDuration(toolCall.duration_ms)}</div>
                      </div>
                      <div>
                        <div className="font-medium text-gray-700">Status:</div>
                        <div className="text-gray-600">{toolCall.status}</div>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};