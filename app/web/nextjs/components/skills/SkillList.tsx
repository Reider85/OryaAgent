'use client';

import { Skill } from '@/types/skill';
import { SkillCard } from './SkillCard';
import { useState } from 'react';

interface SkillListProps {
  skills: Skill[];
  onActivate: (skillName: string) => void;
  loading?: boolean;
  isActivating?: boolean;
}

export function SkillList({ skills, onActivate, loading = false, isActivating = false }: SkillListProps) {
  const [currentPage, setCurrentPage] = useState(1);
  const skillsPerPage = 12;

  if (loading) {
    return (
      <div className="space-y-4">
        {[...Array(6)].map((_, index) => (
          <div key={index} className="border rounded-lg p-4 animate-pulse">
            <div className="flex justify-between items-start">
              <div className="flex-1">
                <div className="h-4 bg-gray-200 rounded mb-2 w-3/4"></div>
                <div className="h-3 bg-gray-200 rounded mb-2 w-full"></div>
                <div className="flex gap-2">
                  <div className="h-6 bg-gray-200 rounded w-16"></div>
                  <div className="h-6 bg-gray-200 rounded w-16"></div>
                </div>
              </div>
              <div className="h-8 bg-gray-200 rounded w-20"></div>
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (skills.length === 0) {
    return (
      <div className="text-center py-12">
        <div className="text-gray-400 text-6xl mb-4">🔍</div>
        <h3 className="text-lg font-medium text-gray-900 mb-2">Навыки не найдены</h3>
        <p className="text-gray-500">Попробуйте изменить параметры поиска или фильтры</p>
      </div>
    );
  }

  const totalPages = Math.ceil(skills.length / skillsPerPage);
  const startIndex = (currentPage - 1) * skillsPerPage;
  const currentSkills = skills.slice(startIndex, startIndex + skillsPerPage);

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {currentSkills.map(skill => (
          <SkillCard
            key={skill.id}
            skill={skill}
            onActivate={onActivate}
            isActivating={isActivating}
          />
        ))}
      </div>

      {totalPages > 1 && (
        <div className="flex justify-center items-center gap-2">
          <button
            onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
            disabled={currentPage === 1}
            className="px-3 py-1 border rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            ←
          </button>
          
          <span className="text-sm text-gray-600">
            Страница {currentPage} из {totalPages}
          </span>
          
          <button
            onClick={() => setCurrentPage(prev => Math.min(totalPages, prev + 1))}
            disabled={currentPage === totalPages}
            className="px-3 py-1 border rounded text-sm disabled:opacity-50 disabled:cursor-not-allowed"
          >
            →
          </button>
        </div>
      )}

      <div className="text-center text-sm text-gray-500">
        Показано {startIndex + 1}-{Math.min(startIndex + skillsPerPage, skills.length)} из {skills.length} навыков
      </div>
    </div>
  );
}