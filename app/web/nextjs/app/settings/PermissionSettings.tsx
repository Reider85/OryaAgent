'use client';

import { useState, useEffect } from 'react';
import { Plus, Trash2, Shield, AlertTriangle } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';

interface PermissionSettingsProps {
  mode: 'strict' | 'permissive';
  allowList: string[];
  onModeChange: (mode: 'strict' | 'permissive') => void;
  onAllowListChange: (allowList: string[]) => void;
}

export function PermissionSettings({ mode, allowList, onModeChange, onAllowListChange }: PermissionSettingsProps) {
  const [newPattern, setNewPattern] = useState('');
  const [error, setError] = useState('');

  const addPattern = () => {
    if (!newPattern.trim()) {
      setError('Pattern cannot be empty');
      return;
    }

    if (allowList.includes(newPattern.trim())) {
      setError('Pattern already exists');
      return;
    }

    const updatedList = [...allowList, newPattern.trim()];
    onAllowListChange(updatedList);
    setNewPattern('');
    setError('');
  };

  const removePattern = (pattern: string) => {
    const updatedList = allowList.filter(p => p !== pattern);
    onAllowListChange(updatedList);
  };

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      addPattern();
    }
  };

  const getModeDescription = () => {
    if (mode === 'strict') {
      return 'Only explicitly allowed patterns are permitted. All other actions are blocked.';
    }
    return 'All actions are permitted except those explicitly denied. More flexible but potentially less secure.';
  };

  return (
    <div className="space-y-6">
      {/* Mode Selection */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Shield className="h-5 w-5" />
          <Label className="text-base font-medium">Permission Mode</Label>
        </div>
        
        <div className="grid grid-cols-1 gap-3">
          <button
            onClick={() => onModeChange('strict')}
            className={`p-4 border rounded-lg text-left transition-colors ${
              mode === 'strict' 
                ? 'border-blue-500 bg-blue-50' 
                : 'border-gray-200 hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className={`w-4 h-4 rounded-full border-2 ${
                mode === 'strict' ? 'border-blue-500 bg-blue-500' : 'border-gray-300'
              }`}>
                {mode === 'strict' && <div className="w-2 h-2 bg-white rounded-full m-0.5" />}
              </div>
              <div>
                <div className="font-medium">Strict Mode</div>
                <div className="text-sm text-gray-600 mt-1">
                  Only explicitly allowed patterns are permitted
                </div>
              </div>
            </div>
          </button>

          <button
            onClick={() => onModeChange('permissive')}
            className={`p-4 border rounded-lg text-left transition-colors ${
              mode === 'permissive' 
                ? 'border-blue-500 bg-blue-50' 
                : 'border-gray-200 hover:border-gray-300'
            }`}
          >
            <div className="flex items-center gap-3">
              <div className={`w-4 h-4 rounded-full border-2 ${
                mode === 'permissive' ? 'border-blue-500 bg-blue-500' : 'border-gray-300'
              }`}>
                {mode === 'permissive' && <div className="w-2 h-2 bg-white rounded-full m-0.5" />}
              </div>
              <div>
                <div className="font-medium">Permissive Mode</div>
                <div className="text-sm text-gray-600 mt-1">
                  All actions permitted except explicitly denied
                </div>
              </div>
            </div>
          </button>
        </div>

        <div className="bg-blue-50 p-4 rounded-lg border border-blue-200">
          <div className="flex gap-2">
            <AlertTriangle className="h-4 w-4 text-blue-600 mt-0.5 flex-shrink-0" />
            <div className="text-sm text-blue-800">
              {getModeDescription()}
            </div>
          </div>
        </div>
      </div>

      {/* Allow List Management */}
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <Label className="text-base font-medium">Allowed Patterns</Label>
          <span className="text-sm text-gray-500">
            {mode === 'strict' ? 'Required in strict mode' : 'Optional in permissive mode'}
          </span>
        </div>

        <div className="space-y-2">
          <div className="flex gap-2">
            <Input
              value={newPattern}
              onChange={(e) => setNewPattern(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Enter pattern (e.g., *.py, read:*.md)"
              className="flex-1"
            />
            <Button onClick={addPattern} size="sm">
              <Plus className="h-4 w-4" />
            </Button>
          </div>
          {error && (
            <div className="text-sm text-red-600">{error}</div>
          )}
        </div>

        {allowList.length > 0 && (
          <div className="space-y-2">
            <Label className="text-sm font-medium text-gray-600">Current Patterns</Label>
            <div className="space-y-1">
              {allowList.map((pattern, index) => (
                <div key={index} className="flex items-center justify-between p-2 bg-gray-50 rounded">
                  <code className="text-sm font-mono">{pattern}</code>
                  <Button
                    onClick={() => removePattern(pattern)}
                    variant="ghost"
                    size="sm"
                    className="h-6 w-6 p-0"
                  >
                    <Trash2 className="h-3 w-3" />
                  </Button>
                </div>
              ))}
            </div>
          </div>
        )}

        {allowList.length === 0 && (
          <div className="text-center py-8 text-gray-500">
            <div className="text-sm">No patterns configured</div>
            <div className="text-xs mt-1">
              {mode === 'strict' 
                ? 'Add patterns to allow specific tools or file types'
                : 'Add patterns to deny specific tools or file types'
              }
            </div>
          </div>
        )}
      </div>

      {/* Pattern Examples */}
      <div className="bg-gray-50 p-4 rounded-lg">
        <Label className="text-sm font-medium mb-2 block">Pattern Examples</Label>
        <div className="grid grid-cols-1 gap-2 text-xs text-gray-600">
          <div><code>*.py</code> - Allow all Python files</div>
          <div><code>read:*.md</code> - Allow reading markdown files</div>
          <div><code>write:src/</code> - Allow writing to src directory</div>
          <div><code>!bash:rm</code> - Deny rm command in bash</div>
        </div>
      </div>
    </div>
  );
}