export interface Skill {
  id: string;
  name: string;
  description: string;
  version: string;
  author: string;
  category: string;
  tags: string[];
  tools: string[];
  hooks: string[];
  dependencies: string[];
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SkillFilters {
  search?: string;
  category?: string;
  tags?: string[];
}

export interface SkillActivationResult {
  success: boolean;
  is_active: boolean;
  message: string;
}