export interface SessionInfo {
  id: string;
  name: string;
  description?: string;
  created_at: string;
  updated_at: string;
  status: 'active' | 'completed' | 'archived';
  message_count: number;
  workspace?: string;
  branch_count?: number;
  last_message?: string;
}

export interface SessionFilter {
  search?: string;
  status?: SessionStatus[];
  limit?: number;
  offset?: number;
}

export type SessionStatus = 'active' | 'completed' | 'archived';

export interface SessionCreateData {
  name: string;
  description?: string;
  workspace?: string;
}

export interface SessionUpdateData {
  name?: string;
  description?: string;
  status?: SessionStatus;
}