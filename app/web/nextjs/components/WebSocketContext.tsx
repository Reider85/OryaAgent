'use client'

import { createContext, useContext, useEffect, useState } from 'react'
import { createWebSocketManager } from './WebSocketProvider'

interface WebSocketContextType {
  websocket: any
  isConnected: boolean
}

const WebSocketContext = createContext<WebSocketContextType | undefined>(undefined)

export function WebSocketProvider({ children }: { children: React.ReactNode }) {
  const [websocket, setWebsocket] = useState<any>(null)
  const [isConnected, setIsConnected] = useState(false)

  useEffect(() => {
    const wsManager = createWebSocketManager()
    setWebsocket(wsManager)

    wsManager.onConnectionStatus((connected: boolean) => {
      setIsConnected(connected)
    })

    return () => {
      wsManager.disconnect()
    }
  }, [])

  return (
    <WebSocketContext.Provider value={{ websocket, isConnected }}>
      {children}
    </WebSocketContext.Provider>
  )
}

export function useWebSocket() {
  const context = useContext(WebSocketContext)
  if (context === undefined) {
    throw new Error('useWebSocket must be used within a WebSocketProvider')
  }
  return context
}