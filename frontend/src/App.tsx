import { useEffect } from 'react';
import AppShell from './components/layout/AppShell';
import MessageStream from './components/layout/MessageStream';
import Composer from './components/layout/Composer';
import PersonaPanel from './components/panels/PersonaPanel';
import MemoryPalacePanel from './components/panels/MemoryPalacePanel';
import KnowledgeBasePanel from './components/panels/KnowledgeBasePanel';
import NotificationsPanel from './components/panels/NotificationsPanel';
import { useChatStore } from './stores/treeStore';

function InspectorPanel() {
  const { inspectorTab, setInspectorTab } = useChatStore();
  
  return (
    <div className="w-80 border-l border-border bg-card flex flex-col">
      <div className="p-2 border-b border-border flex">
        {(['persona', 'memory', 'knowledge', 'notifications'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setInspectorTab(tab)}
            className={`flex-1 px-3 py-1.5 text-sm rounded ${
              inspectorTab === tab
                ? 'bg-secondary text-secondary-foreground'
                : 'hover:bg-accent'
              }`}
          >
            {tab.charAt(0).toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <PersonaPanel />
        <MemoryPalacePanel />
        <KnowledgeBasePanel />
        <NotificationsPanel />
      </div>
    </div>
  );
}

export default function App() {
  const { threads, createThread, activeThreadId, setActiveThread } = useChatStore();
  
  useEffect(() => {
    if (Object.keys(threads).length === 0) {
      const newThreadId = createThread();
      setActiveThread(newThreadId);
    }
  }, [threads, createThread, setActiveThread]);
  
  return (
    <AppShell>
      <div className="flex-1 flex">
        <div className="flex-1 flex flex-col">
          <MessageStream />
          <Composer />
        </div>
        <InspectorPanel />
      </div>
    </AppShell>
  );
}