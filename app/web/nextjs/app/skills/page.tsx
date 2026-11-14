'use client';

import { useState, useEffect } from 'react';
import { Skill, SkillFilters } from '@/types/skill';
import { SkillSearch } from '@/components/skills/SkillSearch';
import { SkillList } from '@/components/skills/SkillList';
import { ToastContainer } from '@/components/Toast';

export default function SkillsPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(false);
  const [isActivating, setIsActivating] = useState(false);
  const [filters, setFilters] = useState<SkillFilters>({});
  const [toasts, setToasts] = useState<Array<{
    id: string;
    message: string;
    type: 'success' | 'error' | 'info';
  }>>([]);

  // Add toast notification
  const addToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    const id = Date.now().toString();
    setToasts(prev => [...prev, { id, message, type }]);
    
    // Auto-remove after 5 seconds
    setTimeout(() => {
      removeToast(id);
    }, 5000);
  };

  // Remove toast notification
  const removeToast = (id: string) => {
    setToasts(prev => prev.filter(toast => toast.id !== id));
  };

  // Fetch skills from API
  const fetchSkills = async (searchFilters: SkillFilters = {}) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (searchFilters.search) params.append('search', searchFilters.search);
      if (searchFilters.category) params.append('category', searchFilters.category);
      if (searchFilters.tags?.length) {
        searchFilters.tags.forEach(tag => params.append('tag', tag));
      }

      const response = await fetch(`/api/skills?${params.toString()}`);
      if (!response.ok) {
        throw new Error('Failed to fetch skills');
      }
      
      const data = await response.json();
      setSkills(data);
    } catch (error) {
      console.error('Error fetching skills:', error);
      addToast('Ошибка при загрузке навыков', 'error');
    } finally {
      setLoading(false);
    }
  };

  // Handle search
  const handleSearch = (query: string) => {
    const newFilters = { ...filters, search: query };
    setFilters(newFilters);
    fetchSkills(newFilters);
  };

  // Handle filter changes
  const handleFilter = (newFilters: { category?: string; tags?: string[] }) => {
    const combinedFilters = { ...filters, ...newFilters };
    setFilters(combinedFilters);
    fetchSkills(combinedFilters);
  };

  // Handle skill activation
  const handleActivate = async (skillName: string) => {
    setIsActivating(true);
    try {
      const response = await fetch(`/api/skills/${skillName}/activate`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('Failed to activate skill');
      }

      const result = await response.json();
      
      // Update local state
      setSkills(prevSkills => 
        prevSkills.map(skill => 
          skill.name === skillName 
            ? { ...skill, is_active: result.is_active }
            : skill
        )
      );

      addToast(result.message, result.is_active ? 'success' : 'info');
    } catch (error) {
      console.error('Error activating skill:', error);
      addToast('Ошибка при активации навыка', 'error');
    } finally {
      setIsActivating(false);
    }
  };

  // Initial fetch
  useEffect(() => {
    fetchSkills();
  }, []);

  return (
    <div className="container mx-auto px-4 py-8">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Навыки</h1>
        <p className="text-gray-600">
          Просматривайте, активируйте и управляйте навыками вашего агента
        </p>
      </div>

      {/* Search and Filters */}
      <div className="mb-8">
        <SkillSearch 
          onSearch={handleSearch}
          onFilter={handleFilter}
        />
      </div>

      {/* Skills List */}
      <div>
        <SkillList 
          skills={skills}
          onActivate={handleActivate}
          loading={loading}
          isActivating={isActivating}
        />
      </div>

      {/* Toast Notifications */}
      <ToastContainer toasts={toasts} onRemove={removeToast} />
    </div>
  );
}