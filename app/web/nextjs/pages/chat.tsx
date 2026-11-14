"""Main chat page for Next.js Web UI with B-15 WebSocket streaming."""

import React, { useState } from 'react';
import { WebSocketProvider } from '../components/WebSocketContext';
import { ChatInterface } from '../components/ChatInterface';
import { SessionSidebar } from '../components/SessionSidebar';
import { ToolCallVisualization } from '../components/ToolCallVisualization';
import { SettingsPanel } from '../components/SettingsPanel';
import { MessageSquare, Settings, Users, Wrench } from 'lucide-react';

interface ChatPageProps {
  session_id: string;
}

export const ChatPage: React.FC<ChatPageProps> = ({ session_id }) => {
  const [activeTab, setActiveTab] = useState<'chat' | 'sessions' | 'tools' | 'settings'>('chat');
  const [currentSessionId, setCurrentSessionId] = useState(session_id);

  const handleConnectionChange = (isConnected: boolean) => {
    console.log('WebSocket connection changed:', isConnected);
  };

  const handleMessage = (message: any) => {
    console.log('Received message:', message);
  };

  const renderContent = () => {
    switch (activeTab) {
      case 'chat':
        return (
          <WebSocketProvider 
            session_id={currentSessionId}
            onConnectionChange={handleConnectionChange}
            onMessage={handleMessage}
          >
            <ChatInterface session_id={currentSessionId} />
          </WebSocketProvider>
        );
      
      case 'sessions':
        return (
          <WebSocketProvider 
            session_id={currentSessionId}
            onConnectionChange={handleConnectionChange}
          >
            <SessionSidebar 
              currentSessionId={currentSessionId}
              onSessionSelect={setCurrentSessionId}
            />
          </WebSocketProvider>
        );
      
      case 'tools':
        return (
          <WebSocketProvider 
            session_id={currentSessionId}
            onConnectionChange={handleConnectionChange}
          >
            <ToolCallVisualization session_id={currentSessionId} />
          </WebSocketProvider>
        );
      
      case 'settings':
        return (
          <WebSocketProvider 
            session_id={currentSessionId}
            onConnectionChange={handleConnectionChange}
          >
            <SettingsPanel />
          </WebSocketProvider>
        );
      
      default:
        return (
          <WebSocketProvider 
            session_id={currentSessionId}
            onConnectionChange={handleConnectionChange}
          >
            <ChatInterface session_id={currentSessionId} />
          </WebSocketProvider>
        );
    }
  };

  return (
    <div className="flex h-screen bg-gray-50">
      {/* Sidebar */}
      <div className="w-64 bg-white border-r flex flex-col">
        <div className="p-6 border-b">
          <h1 className="text-xl font-bold text-gray-900">OryaAgent</h1>
          <p className="text-sm text-gray-600 mt-1">B-15 WebSocket Streaming</p>
        </div>
        
        {/* Navigation */}
        <nav className="flex-1 p-4">
          <button
            onClick={() => setActiveTab('chat')}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg mb-2 ${
              activeTab === 'chat'
                ? 'bg-blue-100 text-blue-700'
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <MessageSquare className="w-5 h-5" />
            <span>Chat</span>
          </button>
          
          <button
            onClick={() => setActiveTab('sessions')}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg mb-2 ${
              activeTab === 'sessions'
                ? 'bg-blue-100 text-blue-700'
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <Users className="w-5 h-5" />
            <span>Sessions</span>
          </button>
          
          <button
            onClick={() => setActiveTab('tools')}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg mb-2 ${
              activeTab === 'tools'
                ? 'bg-blue-100 text-blue-700'
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <Wrench className="w-5 h-5" />
            <span>Tools</span>
          </button>
          
          <button
            onClick={() => setActiveTab('settings')}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-lg ${
              activeTab === 'settings'
                ? 'bg-blue-100 text-blue-700'
                : 'text-gray-700 hover:bg-gray-100'
            }`}
          >
            <Settings className="w-5 h-5" />
            <span>Settings</span>
          </button>
        </nav>
        
        {/* Session info */}
        <div className="p-4 border-t">
          <div className="text-sm text-gray-600">
            <div className="font-medium mb-1">Current Session</div>
            <div className="font-mono text-xs bg-gray-100 px-2 py-1 rounded">
              {currentSessionId}
            </div>
          </div>
        </div>
      </div>
      
      {/* Main content */}
      <div className="flex-1 flex flex-col">
        {renderContent()}
      </div>
    </div>
  );
};

export default ChatPage;