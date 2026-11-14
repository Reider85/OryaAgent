'use client';

import { Skill } from '@/types/skill';

interface SkillDependenciesProps {
  dependencies: string[];
}

export function SkillDependencies({ dependencies }: SkillDependenciesProps) {
  if (dependencies.length === 0) {
    return null;
  }

  return (
    <div className="bg-white rounded-lg shadow-sm border p-6">
      <h2 className="text-xl font-semibold text-gray-900 mb-4 flex items-center gap-2">
        <svg className="w-5 h-5 text-yellow-500" fill="currentColor" viewBox="0 0 20 20">
          <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-11a1 1 0 10-2 0v2H7a1 1 0 100 2h2v2a1 1 0 102 0v-2h2a1 1 0 100-2h-2V7z" clipRule="evenodd" />
        </svg>
        Зависимости
      </h2>
      <div className="space-y-3">
        {dependencies.map((dependency, index) => (
          <div key={index} className="flex items-center justify-between p-3 bg-yellow-50 rounded-lg border border-yellow-200">
            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-yellow-800">{dependency}</span>
              <span className="text-xs text-yellow-600 bg-yellow-100 px-2 py-1 rounded">
                Требуется
              </span>
            </div>
            <button className="text-xs text-yellow-600 hover:text-yellow-800 transition-colors">
              Подробнее
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}