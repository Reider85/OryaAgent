'use client';

import { useState } from 'react';

interface SkillSearchProps {
  onSearch: (query: string) => void;
  onFilter: (filters: { category?: string; tags?: string[] }) => void;
}

const categories = [
  'Development',
  'Code Review', 
  'Testing',
  'DevOps',
  'Documentation',
  'Security',
  'Performance',
  'Architecture'
];

const allTags = [
  'javascript', 'typescript', 'python', 'rust', 'go', 'java',
  'frontend', 'backend', 'fullstack', 'react', 'vue', 'angular',
  'nodejs', 'django', 'flask', 'fastapi', 'spring', 'hibernate',
  'testing', 'unit-testing', 'integration-testing', 'e2e-testing',
  'devops', 'docker', 'kubernetes', 'ci-cd', 'aws', 'gcp',
  'security', 'authentication', 'authorization', 'encryption',
  'performance', 'optimization', 'caching', 'database',
  'architecture', 'design-patterns', 'microservices', 'monolith'
];

export function SkillSearch({ onSearch, onFilter }: SkillSearchProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategory, setSelectedCategory] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);

  const handleSearch = () => {
    onSearch(searchQuery);
  };

  const handleSearchKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      handleSearch();
    }
  };

  const handleCategoryChange = (category: string) => {
    setSelectedCategory(category);
    onFilter({ category, tags: selectedTags });
  };

  const handleTagToggle = (tag: string) => {
    const newTags = selectedTags.includes(tag)
      ? selectedTags.filter(t => t !== tag)
      : [...selectedTags, tag];
    
    setSelectedTags(newTags);
    onFilter({ category: selectedCategory, tags: newTags });
  };

  const clearFilters = () => {
    setSearchQuery('');
    setSelectedCategory('');
    setSelectedTags([]);
    onSearch('');
    onFilter({});
  };

  return (
    <div className="space-y-6">
      {/* Search Input */}
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Поиск навыков по названию или описанию..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyPress={handleSearchKeyPress}
          className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        />
        <button 
          onClick={handleSearch}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors duration-200"
        >
          Поиск
        </button>
      </div>

      {/* Filters */}
      <div className="space-y-4">
        {/* Category Filter */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Категория
          </label>
          <select
            value={selectedCategory}
            onChange={(e) => handleCategoryChange(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
          >
            <option value="">Все категории</option>
            {categories.map(category => (
              <option key={category} value={category}>{category}</option>
            ))}
          </select>
        </div>

        {/* Tags Filter */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-2">
            Теги
          </label>
          <div className="flex flex-wrap gap-2">
            {allTags.map(tag => (
              <button
                key={tag}
                onClick={() => handleTagToggle(tag)}
                className={`px-3 py-1 rounded-full text-sm transition-colors duration-200 ${
                  selectedTags.includes(tag)
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
                }`}
              >
                {tag}
              </button>
            ))}
          </div>
        </div>

        {/* Active Filters */}
        {(selectedCategory || selectedTags.length > 0) && (
          <div className="flex items-center gap-2 p-3 bg-blue-50 rounded-lg">
            <span className="text-sm text-blue-800">Активные фильтры:</span>
            {selectedCategory && (
              <span className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded">
                {selectedCategory}
              </span>
            )}
            {selectedTags.map(tag => (
              <span key={tag} className="px-2 py-1 bg-blue-100 text-blue-800 text-xs rounded">
                {tag}
              </span>
            ))}
            <button
              onClick={clearFilters}
              className="ml-auto text-sm text-blue-600 hover:text-blue-800"
            >
              Очистить
            </button>
          </div>
        )}
      </div>
    </div>
  );
}