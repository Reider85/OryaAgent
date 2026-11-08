import { ChatInterface } from '@/components/ChatInterface'
import { WebSocketProvider } from '@/components/WebSocketProvider'

export default function Home() {
  return (
    <WebSocketProvider>
      <div className="min-h-screen bg-gray-50">
        <ChatInterface />
      </div>
    </WebSocketProvider>
  )
}