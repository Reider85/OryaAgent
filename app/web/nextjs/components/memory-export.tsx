'use client';

import { useState } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Download, FileText, AlertCircle, Eye } from 'lucide-react';

interface ExportData {
  timestamp: string;
  version: string;
  l0_files: Record<string, string>;
  l1_files: Array<{
    name: string;
    entries: Array<any>;
    metadata?: any;
  }>;
}

interface MemoryExportProps {
  session_id: string;
  onExportComplete?: (result: any) => void;
}

export function MemoryExport({ session_id, onExportComplete }: MemoryExportProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [includeL1, setIncludeL1] = useState(true);
  const [isExporting, setIsExporting] = useState(false);
  const [exportData, setExportData] = useState<ExportData | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async () => {
    try {
      setIsExporting(true);
      setError(null);

      const response = await fetch(`/api/memory/export?session_id=${session_id}&include_l1=${includeL1}`, {
        method: 'GET',
      });

      if (!response.ok) {
        throw new Error('Export failed');
      }

      const data = await response.json();
      setExportData(data);
      onExportComplete?.(data);
    } catch (err) {
      setError('Export failed');
      console.error('Export error:', err);
    } finally {
      setIsExporting(false);
    }
  };

  const handleDownload = () => {
    if (!exportData) return;

    const jsonString = JSON.stringify(exportData, null, 2);
    const blob = new Blob([jsonString], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    
    const link = document.createElement('a');
    link.href = url;
    link.download = `memory_export_${new Date().toISOString().split('T')[0]}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const getSummary = () => {
    if (!exportData) return null;

    const l0FileCount = Object.keys(exportData.l0_files).length;
    const l1FileCount = exportData.l1_files.length;
    const totalEntries = exportData.l1_files.reduce((sum, file) => sum + file.entries.length, 0);

    return {
      l0FileCount,
      l1FileCount,
      totalEntries,
    };
  };

  const summary = getSummary();

  return (
    <Dialog open={isOpen} onOpenChange={setIsOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <Download className="w-4 h-4 mr-2" />
          Export Memory
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Export Memory Data</DialogTitle>
          <DialogDescription>
            Export your memory data to a JSON file for backup or sharing.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6">
          {/* Export Options */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Export Options</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <div className="flex items-center space-x-2">
                  <input
                    type="checkbox"
                    id="include-l1"
                    checked={includeL1}
                    onChange={(e) => setIncludeL1(e.target.checked)}
                    className="rounded border-gray-300"
                  />
                  <Label htmlFor="include-l1" className="text-sm">
                    Include L1 Memory Data (SQLite entries)
                  </Label>
                </div>
                <p className="text-xs text-gray-600">
                  L1 data includes detailed memory entries stored in the database. 
                  Deselect to export only L0 files (MD files).
                </p>
              </div>
            </CardContent>
          </Card>

          {/* Export Button */}
          <Button onClick={handleExport} disabled={isExporting} className="w-full">
            {isExporting ? 'Exporting...' : 'Generate Export'}
          </Button>

          {/* Error */}
          {error && (
            <Alert>
              <AlertCircle className="h-4 w-4" />
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}

          {/* Export Results */}
          {exportData && (
            <div className="space-y-4">
              {/* Summary */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base">Export Summary</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-3 gap-2">
                    <div className="text-center">
                      <Badge variant="secondary">{summary?.l0FileCount || 0} L0 Files</Badge>
                    </div>
                    <div className="text-center">
                      <Badge variant="secondary">{summary?.l1FileCount || 0} L1 Files</Badge>
                    </div>
                    <div className="text-center">
                      <Badge variant="secondary">{summary?.totalEntries || 0} Entries</Badge>
                    </div>
                  </div>
                  <div className="mt-3 text-xs text-gray-600">
                    <p>Exported on: {new Date(exportData.timestamp).toLocaleString()}</p>
                    <p>Version: {exportData.version}</p>
                  </div>
                </CardContent>
              </Card>

              {/* L0 Files */}
              {Object.keys(exportData.l0_files).length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base flex items-center gap-2">
                      <FileText className="h-4 w-4" />
                      L0 Memory Files
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {Object.entries(exportData.l0_files).map(([fileName, content]) => (
                        <div key={fileName} className="border rounded p-2">
                          <div className="font-medium text-sm">{fileName}</div>
                          <div className="text-xs text-gray-600 mt-1">
                            {(content.length / 1024).toFixed(1)} KB
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* L1 Files */}
              {exportData.l1_files.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base flex items-center gap-2">
                      <FileText className="h-4 w-4" />
                      L1 Memory Files
                    </CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-2">
                      {exportData.l1_files.map((file) => (
                        <div key={file.name} className="border rounded p-2">
                          <div className="font-medium text-sm">{file.name}</div>
                          <div className="text-xs text-gray-600 mt-1">
                            {file.entries.length} entries
                            {file.metadata && (
                              <span className="ml-2 text-gray-500">
                                ({(file.metadata.size / 1024).toFixed(1)} KB)
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Preview */}
              <Card>
                <CardHeader>
                  <CardTitle className="text-base flex items-center gap-2">
                    <Eye className="h-4 w-4" />
                    JSON Preview
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <pre className="text-xs bg-gray-100 p-3 rounded overflow-x-auto max-h-40">
                    {JSON.stringify(exportData, null, 2)}
                  </pre>
                </CardContent>
              </Card>

              {/* Download Button */}
              <Button onClick={handleDownload} className="w-full">
                <Download className="w-4 h-4 mr-2" />
                Download JSON File
              </Button>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setIsOpen(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}