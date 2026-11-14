'use client';

import { useState, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Upload, FileText, AlertCircle, CheckCircle, XCircle } from 'lucide-react';

interface ImportResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  summary: {
    l0_files: number;
    l1_files: number;
    total_entries: number;
  };
}

interface ImportData {
  l0_files: Record<string, string>;
  l1_files: Array<{
    name: string;
    entries: Array<any>;
    metadata?: any;
  }>;
}

interface MemoryImportProps {
  session_id: string;
  onImportComplete?: (result: any) => void;
}

export function MemoryImport({ session_id, onImportComplete }: MemoryImportProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [importMode, setImportMode] = useState<'overwrite' | 'merge' | 'skip_existing'>('overwrite');
  const [importMethod, setImportMethod] = useState<'file' | 'json'>('file');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [jsonInput, setJsonInput] = useState('');
  const [validationResult, setValidationResult] = useState<ImportResult | null>(null);
  const [isImporting, setIsImporting] = useState(false);
  const [importResult, setImportResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  const handleFileSelect = useCallback((event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setJsonInput('');
      setValidationResult(null);
    }
  }, []);

  const handleJsonChange = useCallback((event: React.ChangeEvent<HTMLTextAreaElement>) => {
    setJsonInput(event.target.value);
    setSelectedFile(null);
    setValidationResult(null);
  }, []);

  const validateImportData = async () => {
    try {
      let sourceData: string;

      if (importMethod === 'file' && selectedFile) {
        const text = await selectedFile.text();
        sourceData = text;
      } else if (importMethod === 'json' && jsonInput.trim()) {
        sourceData = jsonInput;
      } else {
        setError('Please select a file or enter JSON data');
        return;
      }

      const response = await fetch('/api/memory/validate', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          source_file: sourceData,
        }),
      });

      if (!response.ok) {
        throw new Error('Validation failed');
      }

      const result = await response.json();
      setValidationResult(result);
      setError(null);
    } catch (err) {
      setError('Failed to validate import data');
      console.error('Validation error:', err);
    }
  };

  const handleImport = async () => {
    try {
      setIsImporting(true);
      setError(null);
      setImportResult(null);

      let sourceData: string;

      if (importMethod === 'file' && selectedFile) {
        const formData = new FormData();
        formData.append('file', selectedFile);
        formData.append('session_id', session_id);
        formData.append('merge_mode', importMode);

        const response = await fetch('/api/memory/import-upload', {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          throw new Error('Import failed');
        }

        const result = await response.json();
        setImportResult(result);
        onImportComplete?.(result);
      } else if (importMethod === 'json' && jsonInput.trim()) {
        const response = await fetch('/api/memory/import', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            session_id,
            source_file: jsonInput,
            merge_mode,
          }),
        });

        if (!response.ok) {
          throw new Error('Import failed');
        }

        const result = await response.json();
        setImportResult(result);
        onImportComplete?.(result);
      } else {
        setError('Please select a file or enter JSON data');
        return;
      }

      setIsOpen(false);
    } catch (err) {
      setError('Import failed');
      console.error('Import error:', err);
    } finally {
      setIsImporting(false);
    }
  };

  const resetImport = () => {
    setSelectedFile(null);
    setJsonInput('');
    setValidationResult(null);
    setImportResult(null);
    setError(null);
    setImportMode('overwrite');
    setImportMethod('file');
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => {
      setIsOpen(open);
      if (!open) resetImport();
    }}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Upload className="w-4 h-4 mr-2" />
          Import Memory
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Import Memory Data</DialogTitle>
          <DialogDescription>
            Import memory data from a JSON file or paste JSON data directly.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6">
          {/* Import Method Selection */}
          <div className="space-y-3">
            <Label>Import Method</Label>
            <div className="flex gap-2">
              <Button
                variant={importMethod === 'file' ? 'default' : 'outline'}
                onClick={() => setImportMethod('file')}
                size="sm"
              >
                Upload File
              </Button>
              <Button
                variant={importMethod === 'json' ? 'default' : 'outline'}
                onClick={() => setImportMethod('json')}
                size="sm"
              >
                Paste JSON
              </Button>
            </div>
          </div>

          {/* Import Mode Selection */}
          <div className="space-y-3">
            <Label>Import Mode</Label>
            <div className="grid grid-cols-3 gap-2">
              <Button
                variant={importMode === 'overwrite' ? 'default' : 'outline'}
                onClick={() => setImportMode('overwrite')}
                size="sm"
                className="text-xs"
              >
                Overwrite
              </Button>
              <Button
                variant={importMode === 'merge' ? 'default' : 'outline'}
                onClick={() => setImportMode('merge')}
                size="sm"
                className="text-xs"
              >
                Merge
              </Button>
              <Button
                variant={importMode === 'skip_existing' ? 'default' : 'outline'}
                onClick={() => setImportMode('skip_existing')}
                size="sm"
                className="text-xs"
              >
                Skip Existing
              </Button>
            </div>
            <p className="text-xs text-gray-600">
              {importMode === 'overwrite' && 'Replace all existing data'}
              {importMode === 'merge' && 'Add to existing data'}
              {importMode === 'skip_existing' && 'Skip files that already exist'}
            </p>
          </div>

          {/* File Upload */}
          {importMethod === 'file' && (
            <div className="space-y-3">
              <Label>Upload JSON File</Label>
              <div className="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center">
                <input
                  type="file"
                  accept=".json"
                  onChange={handleFileSelect}
                  className="hidden"
                  id="file-upload"
                />
                <label htmlFor="file-upload" className="cursor-pointer">
                  <FileText className="mx-auto h-12 w-12 text-gray-400 mb-2" />
                  <p className="text-sm text-gray-600">
                    {selectedFile ? selectedFile.name : 'Click to upload JSON file'}
                  </p>
                </label>
              </div>
            </div>
          )}

          {/* JSON Input */}
          {importMethod === 'json' && (
            <div className="space-y-3">
              <Label htmlFor="json-input">Paste JSON Data</Label>
              <Textarea
                id="json-input"
                placeholder='{"timestamp": "...", "version": "1.0.0", "l0_files": {}, "l1_files": []}'
                value={jsonInput}
                onChange={handleJsonChange}
                rows={8}
                className="font-mono text-sm"
              />
            </div>
          )}

          {/* Validation */}
          {(selectedFile || jsonInput.trim()) && (
            <div className="space-y-3">
              <Button onClick={validateImportData} variant="outline" className="w-full">
                Validate Data
              </Button>
            </div>
          )}

          {/* Validation Results */}
          {validationResult && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Validation Results</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="flex items-center gap-2">
                  {validationResult.valid ? (
                    <>
                      <CheckCircle className="h-5 w-5 text-green-500" />
                      <span className="text-green-700 font-medium">Valid</span>
                    </>
                  ) : (
                    <>
                      <XCircle className="h-5 w-5 text-red-500" />
                      <span className="text-red-700 font-medium">Invalid</span>
                    </>
                  )}
                </div>

                {validationResult.summary && (
                  <div className="grid grid-cols-3 gap-2">
                    <div className="text-center">
                      <Badge variant="secondary">{validationResult.summary.l0_files} L0 Files</Badge>
                    </div>
                    <div className="text-center">
                      <Badge variant="secondary">{validationResult.summary.l1_files} L1 Files</Badge>
                    </div>
                    <div className="text-center">
                      <Badge variant="secondary">{validationResult.summary.total_entries} Entries</Badge>
                    </div>
                  </div>
                )}

                {validationResult.errors.length > 0 && (
                  <Alert>
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription>
                      <div className="space-y-1">
                        {validationResult.errors.map((error, index) => (
                          <div key={index} className="text-sm">{error}</div>
                        ))}
                      </div>
                    </AlertDescription>
                  </Alert>
                )}

                {validationResult.warnings.length > 0 && (
                  <Alert>
                    <AlertCircle className="h-4 w-4" />
                    <AlertDescription>
                      <div className="space-y-1">
                        {validationResult.warnings.map((warning, index) => (
                          <div key={index} className="text-sm text-yellow-700">{warning}</div>
                        ))}
                      </div>
                    </AlertDescription>
                  </Alert>
                )}
              </CardContent>
            </Card>
          )}

          {/* Import Result */}
          {importResult && (
            <Alert>
              <CheckCircle className="h-4 w-4" />
              <AlertDescription>
                Import completed successfully!
                <div className="mt-2 text-sm space-y-1">
                  <div>L0 files imported: {importResult.l0_files?.imported || 0}</div>
                  <div>L1 files imported: {importResult.l1_files?.imported || 0}</div>
                  <div>Total entries: {importResult.total_entries || 0}</div>
                </div>
              </AlertDescription>
            </Alert>
          )}

          {/* Error */}
          {error && (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setIsOpen(false)}>
            Cancel
          </Button>
          <Button 
            onClick={handleImport} 
            disabled={!selectedFile && !jsonInput.trim() || isImporting || !validationResult?.valid}
          >
            {isImporting ? 'Importing...' : 'Import Data'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}