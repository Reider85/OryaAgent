'use client';

import { useState, useEffect } from 'react';
import { Settings, X, Save, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ModelSelector } from './ModelSelector';
import { PermissionSettings } from './PermissionSettings';

interface SettingsData {
  model: string;
  provider: string;
  permission_mode: 'strict' | 'permissive';
  allow_list: string[];
  budget: number;
}

interface SettingsPanelProps {
  isOpen: boolean;
  onClose: () => void;
}

export function SettingsPanel({ isOpen, onClose }: SettingsPanelProps) {
  const [settings, setSettings] = useState<SettingsData>({
    model: 'claude-3-sonnet-20240229',
    provider: 'anthropic',
    permission_mode: 'permissive',
    allow_list: [],
    budget: 1000,
  });
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  useEffect(() => {
    if (isOpen) {
      fetchSettings();
    }
  }, [isOpen]);

  const fetchSettings = async () => {
    setIsLoading(true);
    try {
      const response = await fetch('/api/settings');
      if (response.ok) {
        const data = await response.json();
        setSettings(data);
      }
    } catch (error) {
      console.error('Error fetching settings:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      const response = await fetch('/api/settings', {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(settings),
      });

      if (response.ok) {
        // Show success message or close panel
        onClose();
      } else {
        throw new Error('Failed to save settings');
      }
    } catch (error) {
      console.error('Error saving settings:', error);
    } finally {
      setIsSaving(false);
    }
  };

  const handleInputChange = (field: keyof SettingsData, value: any) => {
    setSettings(prev => ({ ...prev, [field]: value }));
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 bg-black bg-opacity-50 flex items-center justify-center">
      <div className="bg-white rounded-lg w-full max-w-2xl max-h-[80vh] overflow-hidden">
        <div className="flex items-center justify-between p-6 border-b">
          <div className="flex items-center gap-2">
            <Settings className="h-5 w-5" />
            <h2 className="text-xl font-semibold">Settings</h2>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              onClick={onClose}
              disabled={isSaving}
            >
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={isSaving}
            >
              {isSaving ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <Save className="h-4 w-4 mr-2" />
              )}
              Save
            </Button>
          </div>
        </div>

        <div className="p-6 overflow-y-auto max-h-[60vh]">
          {isLoading ? (
            <div className="flex items-center justify-center h-32">
              <Loader2 className="h-8 w-8 animate-spin" />
            </div>
          ) : (
            <Tabs defaultValue="model" className="w-full">
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="model">Model & Provider</TabsTrigger>
                <TabsTrigger value="permissions">Permissions</TabsTrigger>
              </TabsList>
              
              <TabsContent value="model" className="space-y-4">
                <Card>
                  <CardHeader>
                    <CardTitle>Model Selection</CardTitle>
                    <CardDescription>
                      Choose the AI model and provider for your sessions
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <ModelSelector
                      selectedModel={settings.model}
                      selectedProvider={settings.provider}
                      onModelChange={(model) => handleInputChange('model', model)}
                      onProviderChange={(provider) => handleInputChange('provider', provider)}
                    />
                  </CardContent>
                </Card>

                <Card>
                  <CardHeader>
                    <CardTitle>Budget Settings</CardTitle>
                    <CardDescription>
                      Set your daily budget limit (in USD)
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <div className="flex items-center gap-4">
                      <input
                        type="number"
                        value={settings.budget}
                        onChange={(e) => handleInputChange('budget', Number(e.target.value))}
                        className="flex-1 px-3 py-2 border border-gray-300 rounded-md"
                        min="0"
                        step="100"
                      />
                      <span className="text-sm text-gray-500">USD per day</span>
                    </div>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="permissions" className="space-y-4">
                <Card>
                  <CardHeader>
                    <CardTitle>Permission Mode</CardTitle>
                    <CardDescription>
                      Control how permissions are applied to your sessions
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    <PermissionSettings
                      mode={settings.permission_mode}
                      allowList={settings.allow_list}
                      onModeChange={(mode) => handleInputChange('permission_mode', mode)}
                      onAllowListChange={(allowList) => handleInputChange('allow_list', allowList)}
                    />
                  </CardContent>
                </Card>
              </TabsContent>
            </Tabs>
          )}
        </div>
      </div>
    </div>
  );
}