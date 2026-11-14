'use client';

import { Skill } from '@/types/skill';
import { useState } from 'react';

interface SkillCardProps {
  skill: Skill;
  onActivate: (skillName: string) => void;
  isActivating?: boolean;
}

export function SkillCard({ skill, onActivate, isActivating = false }: SkillCardProps) {
  const [isHovered, setIsHovered] = useState(false);

  return (
    <div 
      className={`border rounded-lg p-4 transition-all duration-200 ${
        isHovered ? 'shadow-md border-blue-300' : 'border-gray-200'
      }`}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <div className="flex justify-between items-start">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-2">
            <h3 className="font-semibold text-lg text-gray-900">{skill.name}</h3>
            <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded-full">
              {skill.category}
            </span>
          </div>
          
          <p className="text-gray-600 text-sm mb-3 line-clamp-2">
            {skill.description}
          </p>
          
          <div className="flex flex-wrap gap-1 mb-3">
            {skill.tags.slice(0, 3).map(tag => (
              <span 
                key={tag} 
                className="px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded-full"
              >
                {tag}
              </span>
            ))}
            {skill.tags.length > 3 && (
              <span className="px-2 py-1 bg-gray-100 text-gray-700 text-xs rounded-full">
                +{skill.tags.length - 3}
              </span>
            )}
          </div>
          
          <div className="flex items-center gap-4 text-xs text-gray-500">
            <span>v{skill.version}</span>
            <span>by {skill.author}</span>
            <span>{skill.tools.length} tools</span>
          </div>
        </div>
        
        <button
          onClick={() => onActivate(skill.name)}
          disabled={isActivating}
          className={`ml-4 px-4 py-2 rounded text-sm font-medium transition-colors duration-200 ${
            skill.is_active 
              ? 'bg-red-100 text-red-700 hover:bg-red-200' 
              : 'bg-green-100 text-green-700 hover:bg-green-200'
          } disabled:opacity-50 disabled:cursor-not-allowed`}
        >
          {isActivating ? 'Обработка...' : skill.is_active ? 'Деактивировать' : 'Активировать'}
        </button>
      </div>
    </div>
  );
}