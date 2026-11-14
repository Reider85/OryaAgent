'use client';

import { useState, useEffect } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { Skill } from '@/types/skill';
import Link from 'next/link';

export default function SkillDetailPage() {
  const params = useParams();
  const router = useRouter();
  const skillName = params.skillName as string;
  
  const [skill, setSkill] = useState<Skill | null>(null);
  const [loading, setLoading] = useState(true);
  const [isActivating, setIsActivating] = useState(false);
  const [activationMessage, setActivationMessage] = useState<string | null>(null);

  useEffect(() => {
    fetchSkill();
  }, [skillName]);

  const fetchSkill = async () => {
    setLoading(true);
    try {
      const response = await fetch(`/api/skills/${skillName}`);
      if (!response.ok) {
        if (response.status === 404) {
          router.push('/skills');
          return;
        }
        throw new Error('Failed to fetch skill');
      }
      
      const data = await response.json();
      setSkill(data);
    } catch (error) {
      console.error('Error fetching skill:', error);
      // TODO: Show error toast
    } finally {
      setLoading(false);
    }
  };

  const handleActivate = async () => {
    if (!skill) return;
    
    setIsActivating(true);
    setActivationMessage(null);
    
    try {
      const response = await fetch(`/api/skills/${skill.name}/activate`, {
        method: 'POST',
      });

      if (!response.ok) {
        throw new Error('Failed to activate skill');
      }

      const result = await response.json();
      setSkill(prev => prev ? { ...prev, is_active: result.is_active } : null);
      setActivationMessage(result.message);
      
      // Clear message after 3 seconds
      setTimeout(() => setActivationMessage(null), 3000);
    } catch (error) {
      console.error('Error activating skill:', error);
      setActivationMessage('Ошибка при активации навыка');
    } finally {
      setIsActivating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600"></div>
      </div>
    );
  }

  if (!skill) {
    return (
      <div className="text-center py-12">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Навык не найден</h2>
        <Link 
          href="/skills" 
          className="text-blue-600 hover:text-blue-800"
        >
          Вернуться к списку навыков
        </Link>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Navigation */}
      <div className="flex items-center gap-4">
        <Link 
          href="/skills" 
          className="flex items-center gap-2 text-blue-600 hover:text-blue-800"
        >
          ← Назад
        </Link>
        <div className="h-6 w-px bg-gray-300"></div>
        <span className="text-sm text-gray-500">Навык: {skill.name}</span>
      </div>

      {/* Header */}
      <div className="bg-white rounded-lg shadow-sm border p-6">
        <div className="flex justify-between items-start mb-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <h1 className="text-2xl font-bold text-gray-900">{skill.name}</h1>
              <span className="px-3 py-1 bg-blue-100 text-blue-800 text-sm rounded-full">
                {skill.category}
              </span>
              <span className="px-3 py-1 bg-gray-100 text-gray-800 text-sm rounded-full">
                v{skill.version}
              </span>
            </div>
            <p className="text-gray-600 mb-4">{skill.description}</p>
            <div className="flex items-center gap-4 text-sm text-gray-500">
              <span>Автор: {skill.author}</span>
              <span>Создан: {new Date(skill.created_at).toLocaleDateString()}</span>
              <span>Обновлён: {new Date(skill.updated_at).toLocaleDateString()}</span>
            </div>
          </div>
          
          <button
            onClick={handleActivate}
            disabled={isActivating}
            className={`px-6 py-3 rounded-lg font-medium transition-colors duration-200 ${
              skill.is_active 
                ? 'bg-red-100 text-red-700 hover:bg-red-200' 
                : 'bg-green-100 text-green-700 hover:bg-green-200'
            } disabled:opacity-50 disabled:cursor-not-allowed`}
          >
            {isActivating ? 'Обработка...' : skill.is_active ? 'Деактивировать' : 'Активировать'}
          </button>
        </div>

        {activationMessage && (
          <div className={`p-3 rounded-lg ${
            skill.is_active ? 'bg-red-50 text-red-700' : 'bg-green-50 text-green-700'
          }`}>
            {activationMessage}
          </div>
        )}
      </div>

      {/* Tools Section */}
      <div className="bg-white rounded-lg shadow-sm border p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Инструменты</h2>
        <div className="grid gap-2">
          {skill.tools.map((tool, index) => (
            <div key={index} className="flex items-center gap-2 p-2 bg-gray-50 rounded">
              <span className="text-sm font-mono text-blue-600">{tool}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Hooks Section */}
      <div className="bg-white rounded-lg shadow-sm border p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Хуки</h2>
        <div className="grid gap-2">
          {skill.hooks.map((hook, index) => (
            <div key={index} className="flex items-center gap-2 p-2 bg-gray-50 rounded">
              <span className="text-sm font-mono text-green-600">{hook}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Stats Section */}
      <SkillStats skill={skill} />

      {/* Dependencies Section */}
      {skill.dependencies.length > 0 && (
        <div className="bg-white rounded-lg shadow-sm border p-6">
          <h2 className="text-xl font-semibold text-gray-900 mb-4">Зависимости</h2>
          <div className="flex flex-wrap gap-2">
            {skill.dependencies.map((dep, index) => (
              <span key={index} className="px-3 py-1 bg-yellow-100 text-yellow-800 text-sm rounded-full">
                {dep}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tags Section */}
      <div className="bg-white rounded-lg shadow-sm border p-6">
        <h2 className="text-xl font-semibold text-gray-900 mb-4">Теги</h2>
        <div className="flex flex-wrap gap-2">
          {skill.tags.map((tag, index) => (
            <span key={index} className="px-3 py-1 bg-purple-100 text-purple-800 text-sm rounded-full">
              {tag}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}