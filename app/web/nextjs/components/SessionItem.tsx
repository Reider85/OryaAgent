
import { Clock, MessageSquare, Folder, MoreVertical } from 'lucide-react';
import { SessionInfo } from '@/types/session';

interface SessionItemProps {
  session: SessionInfo;
  isSelected: boolean;
  onSelect: (sessionId: string) => void;
  onMenuClick?: (session: SessionInfo) => void;
}

const statusColors = {
  active: 'bg-green-100 text-green-800',
  completed: 'bg-blue-100 text-blue-800',
  archived: 'bg-gray-100 text-gray-800',
};

const statusLabels = {
  active: 'Active',
  completed: 'Completed',
  archived: 'Archived',
};

export const SessionItem = ({ 
  session, 
  isSelected, 
  onSelect, 
  onMenuClick 
}: SessionItemProps) => {
  const handleClick = () => {
    onSelect(session.id);
  };

  const handleMenuClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    onMenuClick?.(session);
  };

  return (
    <div
      className={`p-3 rounded-lg cursor-pointer transition-colors ${
        isSelected 
          ? 'bg-blue-50 border border-blue-200' 
          : 'hover:bg-gray-50 border border-transparent'
      }`}
      onClick={handleClick}
    >
      <div className="flex items-start justify-between mb-2">
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-medium text-gray-900 truncate">
            {session.name}
          </h3>
          {session.description && (
            <p className="text-xs text-gray-500 mt-1 truncate">
              {session.description}
            </p>
          )}
        </div>
        <button
          onClick={handleMenuClick}
          className="p-1 hover:bg-gray-200 rounded transition-colors ml-2"
        >
          <MoreVertical className="w-4 h-4 text-gray-400" />
        </button>
      </div>

      <div className="flex items-center gap-4 text-xs text-gray-500">
        <div className="flex items-center gap-1">
          <Clock className="w-3 h-3" />
          <span title={new Date(session.created_at).toLocaleDateString()}>
            {new Date(session.created_at).toLocaleDateString('en-US', { 
              month: 'short', 
              day: 'numeric' 
            })}
          </span>
        </div>
        
        <div className="flex items-center gap-1">
          <MessageSquare className="w-3 h-3" />
          <span>{session.message_count} messages</span>
        </div>

        {session.workspace && (
          <div className="flex items-center gap-1">
            <Folder className="w-3 h-3" />
            <span className="truncate">{session.workspace}</span>
          </div>
        )}
      </div>

      <div className="flex items-center justify-between mt-2">
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${statusColors[session.status]}`}>
          {statusLabels[session.status]}
        </span>
        
        {session.branch_count && session.branch_count > 0 && (
          <span className="text-xs text-gray-500">
            {session.branch_count} branch{session.branch_count > 1 ? 'es' : ''}
          </span>
        )}
      </div>

      {session.last_message && (
        <div className="mt-2 pt-2 border-t border-gray-100">
          <p className="text-xs text-gray-400 truncate">
            Last: {session.last_message}
          </p>
        </div>
      )}
    </div>
  );
};