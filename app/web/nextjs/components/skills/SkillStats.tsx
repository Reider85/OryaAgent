'use client';

import { Skill } from '@/types/skill';

interface SkillStatsProps {
  skill: Skill;
}

export function SkillStats({ skill }: SkillStatsProps) {
  const totalTools = skill.tools.length;
  const totalHooks = skill.hooks.length;
  const totalDependencies = skill.dependencies.length;
  const totalTags = skill.tags.length;

  return (
    <div className="bg-white rounded-lg shadow-sm border p-6">
      <h2 className="text-xl font-semibold text-gray-900 mb-4">Статистика навыка</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="text-center p-4 bg-blue-50 rounded-lg">
          <div className="text-2xl font-bold text-blue-600">{totalTools}</div>
          <div className="text-sm text-blue-800">Инструменты</div>
        </div>
        <div className="text-center p-4 bg-green-50 rounded-lg">
          <div className="text-2xl font-bold text-green-600">{totalHooks}</div>
          <div className="text-sm text-green-800">Хуки</div>
        </div>
        <div className="text-center p-4 bg-yellow-50 rounded-lg">
          <div className="text-2xl font-bold text-yellow-600">{totalDependencies}</div>
          <div className="text-sm text-yellow-800">Зависимости</div>
        </div>
        <div className="text-center p-4 bg-purple-50 rounded-lg">
          <div className="text-2xl font-bold text-purple-600">{totalTags}</div>
          <div className="text-sm text-purple-800">Теги</div>
        </div>
      </div>
      
      <div className="mt-4 pt-4 border-t">
        <div className="flex items-center justify-between">
          <span className="text-sm text-gray-600">Статус:</span>
          <span className={`px-3 py-1 rounded-full text-sm font-medium ${
            skill.is_active 
              ? 'bg-green-100 text-green-800' 
              : 'bg-gray-100 text-gray-800'
          }`}>
            {skill.is_active ? 'Активен' : 'Неактивен'}
          </span>
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-sm text-gray-600">Версия:</span>
          <span className="text-sm font-medium text-gray-900">v{skill.version}</span>
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-sm text-gray-600">Автор:</span>
          <span className="text-sm font-medium text-gray-900">{skill.author}</span>
        </div>
      </div>
    </div>
  );
}