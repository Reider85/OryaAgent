'use client'

import { useState, useEffect } from 'react'
import { ChatInterface } from '@/components/ChatInterface'
import { WebSocketProvider } from '@/components/WebSocketProvider'
import { WebSocketManager } from '@/components/WebSocketProvider'

export default function Home() {
  const [currentSessionId, setCurrentSessionId] = useState<string>('default-session')
  const [websocketManager, setWebsocketManager] = useState<WebSocketManager | null>(null)

  useEffect(() => {
    // Initialize WebSocket manager
    const wsManager = new WebSocketManager()
    setWebsocketManager(wsManager)
    
    return () => {
      wsManager.disconnect()
    }
  }, [])

  const handleSessionChange = (sessionId: string) => {
    setCurrentSessionId(sessionId)
  }

  return (
    <WebSocketProvider>
      <ChatInterface 
        websocket={websocketManager}
        currentSessionId={currentSessionId}
        onSessionChange={handleSessionChange}
      />
    </WebSocketProvider>
  )
}