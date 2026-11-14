"""Settings panel component for Next.js Web UI."""

import React, { useState, useEffect } from 'react';
import { useWebSocket } from '../components/WebSocketContext';
import { Save, RefreshCw, Database, Key, Monitor, Bell } from 'lucide-react';

interface Settings {
  llm_provider: string;
  llm_model: string;
  max_tokens: number;
  temperature: number;
  stream_enabled: boolean;
  auto_save: boolean;
  theme: 'light' | 'dark';
  notifications: boolean;
}

interface SettingsPanelProps {}

export const SettingsPanel: React.FC<SettingsPanelProps> = () => {
  const { isConnected } = useWebSocket();
  const [settings, setSettings] = useState<Settings>({
    llm_provider: 'openai',
    llm_model: 'gpt-3.5-turbo',
    max_tokens: 4000,
    temperature: 0.7,
    stream_enabled: true,
    auto_save: true,
    theme: 'light',
    notifications: true,
  });
  const [loading, setLoading] = useState(false);
  const [saved, setSaved] = useState(false);

  // Load settings from localStorage or API
  useEffect(() => {
    loadSettings();
  }, []);

  const loadSettings = async () => {
    try {
      // Try to load from localStorage first
      const savedSettings = localStorage.getItem('orya_settings');
      if (savedSettings) {
        setSettings(JSON.parse(savedSettings));
      }
      
      // Try to load from API
      const response = await fetch('/api/settings');
      if (response.ok) {
        const apiSettings = await response.json();
        setSettings(prev => ({ ...prev, ...apiSettings }));
      }
    } catch (error) {
      console.error('Failed to load settings:', error);
    }
  };

  const saveSettings = async () => {
    setLoading(true);
    setSaved(false);
    
    try {
      // Save to localStorage
      localStorage.setItem('orya_settings', JSON.stringify(settings));
      
      // Save to API
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(settings),
      });

      if (response.ok) {
        setSaved(true);
        setTimeout(() => setSaved(false), 3000);
      }
    } catch (error) {
      console.error('Failed to save settings:', error);
    } finally {
      setLoading(false);
    }
  };

  const resetSettings = () => {
    setSettings({
      llm_provider: 'openai',
      llm_model: 'gpt-3.5-turbo',
      max_tokens: 4000,
      temperature: 0.7,
      stream_enabled: true,
      auto_save: true,
      theme: 'light',
      notifications: true,
    });
  };

  const handleInputChange = (key: keyof Settings, value: any) => {
    setSettings(prev => ({ ...prev, [key]: value }));
  };

  const llmProviders = [
    { value: 'openai', label: 'OpenAI' },
    { value: 'anthropic', label: 'Anthropic' },
    { value: 'google', label: 'Google' },
    { value: 'deepseek', label: 'DeepSeek' },
  ];

  const llmModels = [
    { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' },
    { value: 'gpt-4', label: 'GPT-4' },
    { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
    { value: 'claude-3-haiku', label: 'Claude 3 Haiku' },
    { value: 'claude-3-sonnet', label: 'Claude 3 Sonnet' },
    { value: 'gemini-pro', label: 'Gemini Pro' },
  ];

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="p-6 border-b">
        <h2 className="text-xl font-bold text-gray-900">Settings</h2>
        <p className="text-sm text-gray-600 mt-1">Configure your OryaAgent experience</p>
      </div>

      {/* Settings form */}
      <div className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl space-y-6">
          {/* LLM Settings */}
          <div className="border rounded-lg p-6">
            <div className="flex items-center gap-2 mb-4">
              <Monitor className="w-5 h-5 text-gray-700" />
              <h3 className="text-lg font-semibold text-gray-900">LLM Settings</h3>
            </div>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Provider
                </label>
                <select
                  value={settings.llm_provider}
                  onChange={(e) => handleInputChange('llm_provider', e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {llmProviders.map(provider => (
                    <option key={provider.value} value={provider.value}>
                      {provider.label}
                    </option>
                  ))}
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Model
                </label>
                <select
                  value={settings.llm_model}
                  onChange={(e) => handleInputChange('llm_model', e.target.value)}
                  className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  {llmModels.map(model => (
                    <option key={model.value} value={model.value}>
                      {model.label}
                    </option>
                  ))}
                </select>
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Max Tokens
                </label>
                <input
                  type="number"
                  value={settings.max_tokens}
                  onChange={(e) => handleInputChange('max_tokens', parseInt(e.target.value))}
                  min="100"
                  max="32000"
                  className="w-full border rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Temperature: {settings.temperature}
                </label>
                <input
                  type="range"
                  value={settings.temperature}
                  onChange={(e) => handleInputChange('temperature', parseFloat(e.target.value))}
                  min="0"
                  max="2"
                  step="0.1"
                  className="w-full"
                />
                <div className="flex justify-between text-xs text-gray-500">
                  <span>0 (Deterministic)</span>
                  <span>1 (Balanced)</span>
                  <span>2 (Creative)</span>
                </div>
              </div>
            </div>
          </div>

          {/* Streaming Settings */}
          <div className="border rounded-lg p-6">
            <div className="flex items-center gap-2 mb-4">
              <RefreshCw className="w-5 h-5 text-gray-700" />
              <h3 className="text-lg font-semibold text-gray-900">Streaming Settings</h3>
            </div>
            
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-gray-700">
                    Enable Real-time Streaming
                  </div>
                  <div className="text-xs text-gray-500">
                    Show responses as they're generated
                  </div>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings.stream_enabled}
                    onChange={(e) => handleInputChange('stream_enabled', e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                </label>
              </div>
              
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-gray-700">
                    Auto-save Messages
                  </div>
                  <div className="text-xs text-gray-500">
                    Automatically save conversation history
                  </div>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings.auto_save}
                    onChange={(e) => handleInputChange('auto_save', e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                </label>
              </div>
            </div>
          </div>

          {/* Appearance Settings */}
          <div className="border rounded-lg p-6">
            <div className="flex items-center gap-2 mb-4">
              <Bell className="w-5 h-5 text-gray-700" />
              <h3 className="text-lg font-semibold text-gray-900">Appearance</h3>
            </div>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  Theme
                </label>
                <div className="flex gap-4">
                  <button
                    onClick={() => handleInputChange('theme', 'light')}
                    className={`flex-1 p-3 border rounded-lg text-center ${
                      settings.theme === 'light'
                        ? 'border-blue-300 bg-blue-50'
                        : 'border-gray-200'
                    }`}
                  >
                    <div className="text-sm font-medium">Light</div>
                  </button>
                  <button
                    onClick={() => handleInputChange('theme', 'dark')}
                    className={`flex-1 p-3 border rounded-lg text-center ${
                      settings.theme === 'dark'
                        ? 'border-blue-300 bg-blue-50'
                        : 'border-gray-200'
                    }`}
                  >
                    <div className="text-sm font-medium">Dark</div>
                  </button>
                </div>
              </div>
              
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-sm font-medium text-gray-700">
                    Enable Notifications
                  </div>
                  <div className="text-xs text-gray-500">
                    Show notifications for important events
                  </div>
                </div>
                <label className="relative inline-flex items-center cursor-pointer">
                  <input
                    type="checkbox"
                    checked={settings.notifications}
                    onChange={(e) => handleInputChange('notifications', e.target.checked)}
                    className="sr-only peer"
                  />
                  <div className="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-300 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-600"></div>
                </label>
              </div>
            </div>
          </div>

          {/* Data Management */}
          <div className="border rounded-lg p-6">
            <div className="flex items-center gap-2 mb-4">
              <Database className="w-5 h-5 text-gray-700" />
              <h3 className="text-lg font-semibold text-gray-900">Data Management</h3>
            </div>
            
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">
                  API Key
                </label>
                <div className="flex gap-2">
                  <input
                    type="password"
                    value="••••••••"
                    readOnly
                    className="flex-1 border rounded-lg px-3 py-2 bg-gray-50"
                  />
                  <button className="bg-blue-600 text-white rounded-lg px-4 py-2 hover:bg-blue-700">
                    <Key className="w-4 h-4" />
                  </button>
                </div>
                <div className="text-xs text-gray-500 mt-1">
                  Click to manage your API keys
                </div>
              </div>
              
              <div className="pt-4 border-t">
                <button
                  onClick={resetSettings}
                  className="w-full bg-gray-100 text-gray-700 rounded-lg px-4 py-2 hover:bg-gray-200 flex items-center justify-center gap-2"
                >
                  <RefreshCw className="w-4 h-4" />
                  <span>Reset to Defaults</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Actions */}
      <div className="border-t p-6">
        <div className="flex items-center justify-between">
          <div className="text-sm text-gray-500">
            {saved ? (
              <span className="text-green-600">✓ Settings saved successfully</span>
            ) : (
              'Changes will be saved automatically'
            )}
          </div>
          
          <div className="flex gap-2">
            <button
              onClick={loadSettings}
              disabled={loading}
              className="bg-gray-100 text-gray-700 rounded-lg px-4 py-2 hover:bg-gray-200 disabled:bg-gray-50 disabled:cursor-not-allowed flex items-center gap-2"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
              <span>Reset</span>
            </button>
            
            <button
              onClick={saveSettings}
              disabled={loading || !isConnected}
              className="bg-blue-600 text-white rounded-lg px-4 py-2 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed flex items-center gap-2"
            >
              <Save className="w-4 h-4" />
              <span>Save Settings</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};