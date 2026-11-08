import { SessionStatus } from '@/types/session';
import { Check, X } from 'lucide-react';

interface SessionFiltersProps {
  selected: SessionStatus[];
  onChange: (selected: SessionStatus[]) => void;
}

const statusOptions: { value: SessionStatus; label: string; color: string }[] = [
  { value: 'active', label: 'Active', color: 'bg-green-100 text-green-800' },
  { value: 'completed', label: 'Completed', color: 'bg-blue-100 text-blue-800' },
  { value: 'archived', label: 'Archived', color: 'bg-gray-100 text-gray-800' },
];

export const SessionFilters = ({ selected, onChange }: SessionFiltersProps) => {
  const toggleStatus = (status: SessionStatus) => {
    if (selected.includes(status)) {
      onChange(selected.filter(s => s !== status));
    } else {
      onChange([...selected, status]);
    }
  };

  const clearAll = () => {
    onChange([]);
  };

  const selectAll = () => {
    onChange(statusOptions.map(option => option.value));
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-gray-700">Filter by status:</span>
        <div className="flex gap-1">
          <button
            onClick={selectAll}
            className="text-xs text-blue-600 hover:text-blue-700 transition-colors"
          >
            Select All
          </button>
          <span className="text-gray-300">|</span>
          <button
            onClick={clearAll}
            className="text-xs text-gray-600 hover:text-gray-700 transition-colors"
          >
            Clear All
          </button>
        </div>
      </div>
      
      <div className="flex flex-wrap gap-2">
        {statusOptions.map((option) => {
          const isSelected = selected.includes(option.value);
          return (
            <button
              key={option.value}
              onClick={() => toggleStatus(option.value)}
              className={`px-3 py-1 rounded-full text-xs font-medium transition-colors ${
                isSelected
                  ? `${option.color} border border-current`
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              <div className="flex items-center gap-1">
                {isSelected && <Check className="w-3 h-3" />}
                {option.label}
              </div>
            </button>
          );
        })}
      </div>
      
      {selected.length > 0 && (
        <div className="text-xs text-gray-500">
          {selected.length} filter{selected.length > 1 ? 's' : ''} applied
        </div>
      )}
    </div>
  );
};