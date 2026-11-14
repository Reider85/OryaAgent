'use client';

import { useState, useEffect } from 'react';
import { ChevronDown, ChevronRight, Loader2, Search, Filter, Clock, CheckCircle, XCircle, AlertCircle } from 'lucide-react';
import { ToolCallNode, ToolCallStats, ToolCallSearchResult } from '@/types/tool-call';

interface ToolCallVisualizationProps {
  sessionId: string;
  className?: string;
}

interface ToolCallTreeNode extends ToolCallNode {
  depth: number;
  isExpanded: boolean;
}

export function ToolCallVisualization({ sessionId, className = '' }: ToolCallVisualizationProps) {
  const [toolCallTree, setToolCallTree] = useState<ToolCallTreeNode[]>([]);
  const [stats, setStats] = useState<ToolCallStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());
  const [filterStatus, setFilterStatus] = useState<string>('all');

  // Load tool call data
  useEffect(() => {
    loadToolCallData();
  }, [sessionId]);

  const loadToolCallData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Load tree data
      const treeResponse = await fetch(`/ui/api/sessions/${sessionId}/tool-calls/tree`);
      if (!treeResponse.ok) {
        throw new Error('Failed to load tool call tree');
      }
      const treeData = await treeResponse.json();
      
      // Load statistics
      const statsResponse = await fetch(`/ui/api/sessions/${sessionId}/tool-calls/statistics`);
      if (statsResponse.ok) {
        const statsData = await statsResponse.json();
        setStats(statsData);
      }

      // Convert to tree nodes with expanded state
      const treeWithExpanded = treeData.map((node: ToolCallNode) => 
        convertToTreeNode(node, 0, true)
      );
      
      setToolCallTree(treeWithExpanded);
    } catch (err) {
      console.error('Error loading tool call data:', err);
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  const convertToTreeNode = (node: ToolCallNode, depth: number, isExpanded: boolean): ToolCallTreeNode => ({
    ...node,
    depth,
    isExpanded,
  });

  const toggleNode = (nodeId: string) => {
    setExpandedNodes(prev => {
      const newSet = new Set(prev);
      if (newSet.has(nodeId)) {
        newSet.delete(nodeId);
      } else {
        newSet.add(nodeId);
      }
      return newSet;
    });
  };

  const filteredTree = filterTree(toolCallTree, searchQuery, filterStatus);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />;
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-500" />;
      case 'error':
        return <AlertCircle className="h-4 w-4 text-red-500" />;
      case 'running':
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />;
      default:
        return <div className="h-4 w-4 rounded-full bg-gray-400" />;
    }
  };

  const formatDuration = (durationMs?: number) => {
    if (!durationMs) return 'N/A';
    if (durationMs < 1000) {
      return `${durationMs.toFixed(2)}ms`;
    }
    return `${(durationMs / 1000).toFixed(2)}s`;
  };

  const formatJson = (obj: any, maxLength = 100) => {
    try {
      const str = JSON.stringify(obj, null, 2);
      if (str.length > maxLength) {
        return str.substring(0, maxLength) + '...';
      }
      return str;
    } catch {
      return String(obj);
    }
  };

  const renderTreeNode = (node: ToolCallTreeNode) => {
    const isExpanded = expandedNodes.has(node.id);
    const hasChildren = node.children.length > 0;
    const indent = node.depth * 20;

    return (
      <div key={node.id} className="border-l border-gray-200 ml-2">
        <div 
          className="flex items-start space-x-2 py-2 hover:bg-gray-50 cursor-pointer"
          style={{ marginLeft: `${indent}px` }}
          onClick={() => hasChildren && toggleNode(node.id)}
        >
          {hasChildren ? (
            isExpanded ? (
              <ChevronDown className="h-4 w-4 text-gray-400 mt-0.5 flex-shrink-0" />
            ) : (
              <ChevronRight className="h-4 w-4 text-gray-400 mt-0.5 flex-shrink-0" />
            )
          ) : (
            <div className="w-4 h-4 mt-0.5 flex-shrink-0" />
          )}
          
          <div className="flex items-center space-x-2 flex-1 min-w-0">
            {getStatusIcon(node.status)}
            <div className="flex-1 min-w-0">
              <div className="flex items-center space-x-2">
                <span className="font-medium text-sm text-gray-900 truncate">
                  {node.name}
                </span>
                <span className="text-xs text-gray-500">
                  {formatDuration(node.duration_ms)}
                </span>
              </div>
              <div className="text-xs text-gray-500 mt-1">
                {new Date(node.start_time).toLocaleTimeString()}
              </div>
            </div>
          </div>
        </div>

        {isExpanded && (
          <div className="ml-4 space-y-2">
            {/* Arguments */}
            {node.arguments && Object.keys(node.arguments).length > 0 && (
              <div className="bg-gray-50 rounded-md p-3">
                <div className="text-xs font-medium text-gray-700 mb-1">Arguments</div>
                <pre className="text-xs text-gray-600 overflow-x-auto">
                  {formatJson(node.arguments)}
                </pre>
              </div>
            )}

            {/* Result */}
            {node.result && (
              <div className="bg-green-50 rounded-md p-3">
                <div className="text-xs font-medium text-green-700 mb-1">Result</div>
                <pre className="text-xs text-green-600 overflow-x-auto">
                  {formatJson(node.result)}
                </pre>
              </div>
            )}

            {/* Error */}
            {node.error && (
              <div className="bg-red-50 rounded-md p-3">
                <div className="text-xs font-medium text-red-700 mb-1">Error</div>
                <pre className="text-xs text-red-600 overflow-x-auto">
                  {node.error}
                </pre>
              </div>
            )}

            {/* Children */}
            {node.children.map(child => renderTreeNode(convertToTreeNode(child, node.depth + 1, isExpanded)))}
          </div>
        )}
      </div>
    );
  };

  const filterTree = (nodes: ToolCallTreeNode[], query: string, status: string): ToolCallTreeNode[] => {
    return nodes
      .filter(node => {
        // Status filter
        if (status !== 'all' && node.status !== status) {
          return false;
        }
        
        // Search filter
        if (query) {
          const queryLower = query.toLowerCase();
          const matchesName = node.name.toLowerCase().includes(queryLower);
          const matchesArgs = Object.values(node.arguments).some(arg => 
            String(arg).toLowerCase().includes(queryLower)
          );
          if (!matchesName && !matchesArgs) {
            return false;
          }
        }
        
        return true;
      })
      .map(node => ({
        ...node,
        children: filterTree(node.children, query, status),
        isExpanded: query ? true : node.isExpanded,
      }));
  };

  if (loading) {
    return (
      <div className={`bg-white rounded-lg shadow-sm border border-gray-200 ${className}`}>
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-gray-400" />
          <span className="ml-2 text-gray-500">Loading tool calls...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className={`bg-white rounded-lg shadow-sm border border-gray-200 ${className}`}>
        <div className="flex items-center justify-center h-64">
          <div className="text-center text-red-500">
            <div className="text-lg font-medium">Error loading tool calls</div>
            <div className="text-sm mt-1">{error}</div>
            <button 
              onClick={loadToolCallData}
              className="mt-2 px-3 py-1 text-sm bg-red-600 text-white rounded hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`bg-white rounded-lg shadow-sm border border-gray-200 ${className}`}>
      {/* Header */}
      <div className="border-b border-gray-200 p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-gray-900">Tool Call Visualization</h2>
          <button
            onClick={loadToolCallData}
            className="px-3 py-1 text-sm bg-gray-100 text-gray-700 rounded hover:bg-gray-200"
          >
            Refresh
          </button>
        </div>

        {/* Filters */}
        <div className="flex items-center space-x-4">
          <div className="flex items-center space-x-2">
            <Search className="h-4 w-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search tool calls..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
            />
          </div>

          <div className="flex items-center space-x-2">
            <Filter className="h-4 w-4 text-gray-400" />
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="px-2 py-1 text-sm border border-gray-300 rounded focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="all">All Status</option>
              <option value="completed">Completed</option>
              <option value="failed">Failed</option>
              <option value="error">Error</option>
              <option value="running">Running</option>
            </select>
          </div>
        </div>
      </div>

      {/* Statistics */}
      {stats && (
        <div className="border-b border-gray-200 p-4">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-gray-900">{stats.total_calls}</div>
              <div className="text-sm text-gray-500">Total Calls</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-green-600">{stats.successful_calls}</div>
              <div className="text-sm text-gray-500">Successful</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-red-600">{stats.failed_calls}</div>
              <div className="text-sm text-gray-500">Failed</div>
            </div>
            <div className="text-center">
              <div className="text-2xl font-bold text-blue-600">
                {(stats.success_rate * 100).toFixed(1)}%
              </div>
              <div className="text-sm text-gray-500">Success Rate</div>
            </div>
          </div>
        </div>
      )}

      {/* Tree */}
      <div className="p-4 max-h-96 overflow-y-auto">
        {filteredTree.length === 0 ? (
          <div className="text-center text-gray-500 py-8">
            No tool calls found
          </div>
        ) : (
          <div className="space-y-1">
            {filteredTree.map(node => renderTreeNode(node))}
          </div>
        )}
      </div>
    </div>
  );
}