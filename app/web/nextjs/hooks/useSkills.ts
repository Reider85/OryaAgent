'use client';

import { useState, useEffect, useCallback } from 'react';
import { Skill, SkillFilters, SkillActivationResult } from '@/types/skill';
import { getSkills, activateSkill } from '@/lib/api/skills';

export function useSkills() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch skills with filters
  const fetchSkills = useCallback(async (filters: SkillFilters = {}) => {
    setLoading(true);
    setError(null);
    
    try {
      const data = await getSkills(filters);
      setSkills(data);
    } catch (err) {
      setError('Failed to fetch skills');
      console.error('Error fetching skills:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Activate or deactivate a skill
  const toggleSkillActivation = useCallback(async (skillName: string) => {
    try {
      const result: SkillActivationResult = await activateSkill(skillName);
      
      // Update local state
      setSkills(prevSkills => 
        prevSkills.map(skill => 
          skill.name === skillName 
            ? { ...skill, is_active: result.is_active }
            : skill
        )
      );

      return result;
    } catch (err) {
      const errorMessage = 'Failed to toggle skill activation';
      setError(errorMessage);
      console.error('Error toggling skill activation:', err);
      throw new Error(errorMessage);
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  return {
    skills,
    loading,
    error,
    fetchSkills,
    toggleSkillActivation
  };
}