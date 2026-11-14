import { SettingsPanel } from '@/app/settings/SettingsPanel';

export default function SettingsPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <SettingsPanel 
        isOpen={true} 
        onClose={() => window.history.back()} 
      />
    </div>
  );
}