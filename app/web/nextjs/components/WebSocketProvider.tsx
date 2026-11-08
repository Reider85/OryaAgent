'use client'

import { useEffect, useRef, useState } from 'react'

export interface Message {
  id: string
  type: 'user' | 'assistant' | 'error' | 'tool_call' | 'tool_result' | 'stream_token' | 'connection'
  content: string
  timestamp: string
  role?: 'user' | 'assistant' | 'system'
  session_id?: string
  tool_name?: string
  tool_args?: any
  tool_result?: any
  request_id?: string
  position?: number
  total_tokens?: number
}

export interface WebSocketManager {
  connect: (sessionId: string) => Promise<void>
  disconnect: () => void
  sendMessage: (message: any) => Promise<void>
  onMessage: (callback: (message: Message) => void) => void
  onConnectionStatus: (callback: (connected: boolean) => void) => void
}

export function createWebSocketManager(): WebSocketManager {
  let ws: WebSocket | null = null
  let messageCallback: ((message: Message) => void) | null = null
  let connectionStatusCallback: ((connected: boolean) => void) | null = null
  let reconnectTimeout: NodeJS.Timeout | null = null
  let isConnected = false

  const connect = async (sessionId: string): Promise<void> => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      return
    }

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${window.location.host}/ws/${sessionId}`
    
    ws = new WebSocket(url)

    ws.onopen = () => {
      isConnected = true
      connectionStatusCallback?.(true)
      console.log('WebSocket connected')
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const message: Message = {
          id: data.message_id || `msg-${Date.now()}`,
          type: data.type,
          content: data.content || data.message || '',
          timestamp: new Date().toISOString(),
          role: data.role,
          session_id: data.session_id,
          tool_name: data.tool_name,
          tool_args: data.arguments,
          tool_result: data.result,
          request_id: data.request_id,
          position: data.position,
          total_tokens: data.total_tokens,
        }
        messageCallback?.(message)
      } catch (error) {
        console.error('Error parsing WebSocket message:', error)
      }
    }

    ws.onclose = () => {
      isConnected = false
      connectionStatusCallback?.(false)
      console.log('WebSocket disconnected')
      
      // Attempt to reconnect after 3 seconds
      if (reconnectTimeout) {
        clearTimeout(reconnectTimeout)
      }
      reconnectTimeout = setTimeout(() => {
        connect(sessionId)
      }, 3000)
    }

    ws.onerror = (error) => {
      console.error('WebSocket error:', error)
      connectionStatusCallback?.(false)
    }
  }

  const disconnect = () => {
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout)
      reconnectTimeout = null
    }
    
    if (ws) {
      ws.close()
      ws = null
    }
    isConnected = false
    connectionStatusCallback?.(false)
  }

  const sendMessage = async (message: any): Promise<void> => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected')
    }

    ws.send(JSON.stringify(message))
  }

  const onMessage = (callback: (message: Message) => void) => {
    messageCallback = callback
  }

  const onConnectionStatus = (callback: (connected: boolean) => void) => {
    connectionStatusCallback = callback
  }

  return {
    connect,
    disconnect,
    sendMessage,
    onMessage,
    onConnectionStatus,
  }
}

// Hook for using WebSocket
export function useWebSocket(sessionId: string) {
  const [messages, setMessages] = useState<Message[]>([])
  const [isConnected, setIsConnected] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  
  const websocketManager = useRef<WebSocketManager | null>(null)

  useEffect(() => {
    if (!websocketManager.current) {
      websocketManager.current = createWebSocketManager()
    }

    const ws = websocketManager.current

    ws.connect(sessionId)
    
    ws.onMessage((message) => {
      setMessages(prev => [...prev, message])
    })

    ws.onConnectionStatus((connected) => {
      setIsConnected(connected)
    })

    return () => {
      ws.disconnect()
    }
  }, [sessionId])

  const sendMessage = async (content: string) => {
    if (!websocketManager.current || !isConnected) return

    setIsLoading(true)
    
    try {
      await websocketManager.current.sendMessage({
        type: 'message',
        content,
        session_id: sessionId
      })
    } catch (error) {
      console.error('Error sending message:', error)
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

  return {
    messages,
    isConnected,
    isLoading,
    sendMessage,
  }
}