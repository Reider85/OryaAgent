'use client'

import { useState, useEffect } from 'react'
import { Send, Bot, User, Loader2, Settings, ChevronDown, ChevronUp } from 'lucide-react'
import { Message, WebSocketManager } from './WebSocketProvider'
import { SettingsPanel } from '@/app/settings/SettingsPanel'
import { ToolCallVisualization } from './ToolCallVisualization'

interface ChatInterfaceProps {
  websocket?: WebSocketManager
  currentSessionId?: string
  onSessionChange?: (sessionId: string) => void
}

export function ChatInterface({ 
  websocket: propWebSocket, 
  currentSessionId = 'default-session',
  onSessionChange 
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputValue, setInputValue] = useState('')
  const [isConnected, setIsConnected] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [internalSessionId, setInternalSessionId] = useState<string>(currentSessionId)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)
  const [showToolCalls, setShowToolCalls] = useState(false)
  
  const websocket = propWebSocket || new WebSocketManager()

  useEffect(() => {
    // Update internal session ID when prop changes
    if (currentSessionId !== internalSessionId) {
      setInternalSessionId(currentSessionId)
      setMessages([]) // Clear messages when switching sessions
    }
  }, [currentSessionId, internalSessionId])

  useEffect(() => {
    // Initialize WebSocket connection
    websocket.connect(internalSessionId)
    setIsConnected(true)

    // Listen for messages
    websocket.onMessage((message: Message) => {
      setMessages(prev => [...prev, message])
    })

    // Listen for connection status
    websocket.onConnectionStatus((connected: boolean) => {
      setIsConnected(connected)
    })

    // Cleanup on unmount
    return () => {
      websocket.disconnect()
    }
  }, [websocket, internalSessionId])

  const handleSendMessage = async () => {
    if (!inputValue.trim() || isLoading) return

    const userMessage: Message = {
      id: `msg-${Date.now()}`,
      type: 'user',
      content: inputValue,
      timestamp: new Date().toISOString(),
      role: 'user'
    }

    setMessages(prev => [...prev, userMessage])
    setInputValue('')
    setIsLoading(true)

    try {
      await websocket.sendMessage({
        type: 'message',
        content: inputValue,
        session_id: currentSessionId
      })
    } catch (error) {
      console.error('Error sending message:', error)
      // Add error message
      setMessages(prev => [...prev, {
        id: `msg-error-${Date.now()}`,
        type: 'error',
        content: 'Failed to send message. Please try again.',
        timestamp: new Date().toISOString(),
        role: 'system'
      }])
    } finally {
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  const createNewSession = async () => {
    try {
      const response = await fetch('/web/api/sessions', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      })
      
      if (response.ok) {
        const data = await response.json()
        setInternalSessionId(data.id)
        onSessionChange?.(data.id)
        setMessages([]) // Clear messages for new session
      }
    } catch (error) {
      console.error('Error creating session:', error)
    }
  }

  return (
    <div className="flex flex-col h-screen">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 px-4 py-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center space-x-3">
            <Bot className="h-6 w-6 text-blue-600" />
            <h1 className="text-xl font-semibold text-gray-900">OryaAgent</h1>
            <div className="flex items-center space-x-2">
              <div className={`h-2 w-2 rounded-full ${isConnected ? 'bg-green-500' : 'bg-red-500'}`}></div>
              <span className="text-sm text-gray-500">
                {isConnected ? 'Connected' : 'Disconnected'}
              </span>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <span className="text-sm text-gray-500">Session: {currentSessionId}</span>
            <button
              onClick={() => setIsSettingsOpen(true)}
              className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-md transition-colors"
              title="Settings"
            >
              <Settings className="h-5 w-5" />
            </button>
            <button
              onClick={() => setShowToolCalls(!showToolCalls)}
              className="px-3 py-1 text-sm bg-green-600 text-white rounded-md hover:bg-green-700 transition-colors"
            >
              {showToolCalls ? 'Hide' : 'Show'} Tool Calls
            </button>
            <button
              onClick={createNewSession}
              className="px-3 py-1 text-sm bg-blue-600 text-white rounded-md hover:bg-blue-700 transition-colors"
            >
              New Session
            </button>
          </div>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center text-gray-500">
              <Bot className="h-12 w-12 mx-auto mb-4 text-gray-400" />
              <h3 className="text-lg font-medium mb-2">Welcome to OryaAgent</h3>
              <p className="text-sm">Start a conversation by typing a message below.</p>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
            >
              <div
                className={`max-w-3xl rounded-lg px-4 py-3 ${
                  message.role === 'user'
                    ? 'bg-blue-600 text-white'
                    : message.type === 'error'
                    ? 'bg-red-100 text-red-900'
                    : 'bg-gray-100 text-gray-900'
                }`}
              >
                <div className="flex items-start space-x-2">
                  {message.role === 'assistant' && <Bot className="h-5 w-5 mt-0.5 flex-shrink-0" />}
                  {message.role === 'user' && <User className="h-5 w-5 mt-0.5 flex-shrink-0" />}
                  <div className="flex-1">
                    <div className="text-sm font-medium mb-1">
                      {message.role === 'user' ? 'You' : 'OryaAgent'}
                    </div>
                    <div className="text-sm whitespace-pre-wrap">{message.content}</div>
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
        
        {isLoading && (
          <div className="flex justify-start">
            <div className="bg-gray-100 rounded-lg px-4 py-3">
              <div className="flex items-center space-x-2">
                <Loader2 className="h-5 w-5 animate-spin text-gray-500" />
                <span className="text-sm text-gray-500">OryaAgent is thinking...</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Tool Call Visualization Panel */}
      {showToolCalls && (
        <div className="border-t border-gray-200 bg-gray-50">
          <div className="p-4 border-b border-gray-200">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-gray-900">Tool Call Visualization</h3>
              <button
                onClick={() => setShowToolCalls(false)}
                className="p-1 hover:bg-gray-200 rounded"
              >
                <ChevronUp className="h-4 w-4 text-gray-500" />
              </button>
            </div>
          </div>
          <div className="p-4">
            <ToolCallVisualization sessionId={internalSessionId} />
          </div>
        </div>
      )}

      {/* Input */}
      <div className="bg-white border-t border-gray-200 p-4">
        <div className="flex items-end space-x-2">
          <div className="flex-1">
            <textarea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Type your message..."
              className="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent resize-none"
              rows={2}
              disabled={isLoading}
            />
          </div>
          <button
            onClick={handleSendMessage}
            disabled={!inputValue.trim() || isLoading}
            className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors"
          >
            <Send className="h-5 w-5" />
          </button>
        </div>
      </div>

      {/* Settings Panel */}
      <SettingsPanel
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />
    </div>
  )
}