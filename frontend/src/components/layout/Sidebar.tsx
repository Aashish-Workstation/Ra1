import { Plus, Search, MoreHorizontal, MessageCircle } from 'lucide-react';
import { useChatStore } from '../../stores/treeStore';

export default function Sidebar({ open, onToggle }: { open: boolean; onToggle: (o: boolean) => void }) {
  const { threads, activeThreadId, setActiveThread, createThread, deleteThread } = useChatStore();
  const threadList = Object.values(threads);

  return (
    <div className={`w-64 border-r border-border bg-card transition-transform duration-200 ${
      open ? 'translate-x-0' : '-translate-x-full'
    }`}>
      <div className="p-3 border-b border-border">
        <button
          onClick={createThread}
          className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity"
        >
          <Plus size={16} />
          New Thread
        </button>
      </div>
      <div className="p-2">
        <div className="relative mb-2">
          <Search size={14} className="absolute left-2 top-2.5 text-muted-foreground" />
          <input
            type="text"
            placeholder="Search threads..."
            className="w-full pl-8 pr-2 py-1.5 text-sm bg-input rounded-md border border-border outline-none"
          />
        </div>
        <div className="space-y-1">
          {threadList.map((thread) => (
            <div
              key={thread.thread_id}
              className={`group flex items-center gap-2 px-3 py-2 text-sm rounded-lg cursor-pointer transition-colors ${
                activeThreadId === thread.thread_id
                  ? 'bg-secondary text-secondary-foreground'
                  : 'hover:bg-accent hover:text-accent-foreground'
              }`}
              onClick={() => setActiveThread(thread.thread_id)}
            >
              <MessageCircle size={14} />
              <span className="flex-1 truncate">Thread {thread.thread_id.slice(0, 8)}</span>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  deleteThread(thread.thread_id);
                }}
                className="opacity-0 group-hover:opacity-100 transition-opacity"
              >
                <MoreHorizontal size={14} />
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}