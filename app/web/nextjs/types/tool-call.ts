export interface ToolCallNode {
  id: string;
  name: string;
  arguments: Record<string, any>;
  start_time: string;
  end_time?: string;
  duration_ms?: number;
  status: 'running' | 'completed' | 'failed' | 'error';
  result?: any;
  error?: string;
  children: ToolCallNode[];
}

export interface ToolCallStats {
  total_calls: number;
  successful_calls: number;
  failed_calls: number;
  success_rate: number;
  average_duration_ms: number;
  tool_counts: Record<string, number>;
  status_counts: Record<string, number>;
}

export interface ToolCallSearchResult {
  id: string;
  name: string;
  arguments: Record<string, any>;
  start_time: string;
  end_time?: string;
  duration_ms?: number;
  status: string;
  result?: any;
  error?: string;
  children: ToolCallNode[];
}

export interface FormattedToolCall {
  id: string;
  name: string;
  arguments: Record<string, any>;
  start_time: string;
  end_time?: string;
  duration: string;
  status: string;
  result?: any;
  error?: string;
}