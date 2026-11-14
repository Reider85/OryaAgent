'use client';

import { useState, useEffect } from 'react';
import { ChevronDown, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';

interface Model {
  id: string;
  name: string;
  provider: string;
  max_tokens: number;
  cost_per_1k_input: number;
  cost_per_1k_output: number;
  description: string;
  category: string;
}

interface ModelSelectorProps {
  selectedModel: string;
  selectedProvider: string;
  onModelChange: (model: string) => void;
  onProviderChange: (provider: string) => void;
}

export function ModelSelector({ selectedModel, selectedProvider, onModelChange, onProviderChange }: ModelSelectorProps) {
  const [models, setModels] = useState<Model[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [isProviderOpen, setIsProviderOpen] = useState(false);
  const [isModelOpen, setIsModelOpen] = useState(false);

  useEffect(() => {
    fetchModels();
  }, []);

  const fetchModels = async () => {
    try {
      const response = await fetch('/api/models');
      if (response.ok) {
        const data = await response.json();
        setModels(data);
      }
    } catch (error) {
      console.error('Error fetching models:', error);
    } finally {
      setIsLoading(false);
    }
  };

  const filteredModels = models.filter(model =>
    model.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    model.provider.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const providers = [...new Set(models.map(model => model.provider))];

  const selectedModelData = models.find(model => model.id === selectedModel);
  const selectedProviderData = providers.find(provider => provider === selectedProvider);

  return (
    <div className="space-y-4">
      {/* Provider Selection */}
      <div className="space-y-2">
        <label className="text-sm font-medium">Provider</label>
        <div className="relative">
          <Button
            variant="outline"
            onClick={() => setIsProviderOpen(!isProviderOpen)}
            className="w-full justify-between"
          >
            {selectedProviderData || selectedProvider || 'Select provider'}
            <ChevronDown className="h-4 w-4" />
          </Button>
          
          {isProviderOpen && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-white border rounded-md shadow-lg z-10">
              {providers.map(provider => (
                <button
                  key={provider}
                  onClick={() => {
                    onProviderChange(provider);
                    setIsProviderOpen(false);
                  }}
                  className={`w-full px-4 py-2 text-left hover:bg-gray-50 flex items-center gap-2 ${
                    provider === selectedProvider ? 'bg-blue-50' : ''
                  }`}
                >
                  {provider === selectedProvider && <Check className="h-4 w-4" />}
                  {provider}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Model Selection */}
      <div className="space-y-2">
        <label className="text-sm font-medium">Model</label>
        <div className="relative">
          <Input
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="Search models..."
            className="w-full"
          />
          
          {searchTerm && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-white border rounded-md shadow-lg z-10 max-h-60 overflow-y-auto">
              {isLoading ? (
                <div className="p-4 text-center">Loading models...</div>
              ) : filteredModels.length === 0 ? (
                <div className="p-4 text-center text-gray-500">No models found</div>
              ) : (
                filteredModels.map(model => (
                  <button
                    key={model.id}
                    onClick={() => {
                      onModelChange(model.id);
                      setSearchTerm('');
                      setIsModelOpen(false);
                    }}
                    className={`w-full px-4 py-3 text-left hover:bg-gray-50 flex items-start gap-3 ${
                      model.id === selectedModel ? 'bg-blue-50' : ''
                    }`}
                  >
                    <div className="flex-1">
                      <div className="font-medium">{model.name}</div>
                      <div className="text-sm text-gray-500">{model.provider}</div>
                      <div className="text-xs text-gray-400 mt-1">{model.description}</div>
                    </div>
                    {model.id === selectedModel && <Check className="h-4 w-4 mt-1" />}
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </div>

      {/* Selected Model Info */}
      {selectedModelData && (
        <div className="bg-gray-50 p-4 rounded-md">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <div>
              <span className="font-medium">Max Tokens:</span> {selectedModelData.max_tokens}
            </div>
            <div>
              <span className="font-medium">Input Cost:</span> ${selectedModelData.cost_per_1k_input}/1K tokens
            </div>
            <div>
              <span className="font-medium">Output Cost:</span> ${selectedModelData.cost_per_1k_output}/1K tokens
            </div>
            <div>
              <span className="font-medium">Category:</span> {selectedModelData.category}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}