import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useChatStore } from '../../stores/treeStore';

type BranchSelectorProps = {
  nodeId: string;
};

export function BranchSelector({ nodeId }: BranchSelectorProps) {
  const { threads, activeThreadId, switchBranch, branchFromNode } = useChatStore();
  const thread = activeThreadId ? threads[activeThreadId] : null;
  const node = thread?.nodes[nodeId];
  
  if (!node || node.children_ids.length === 0) return null;

  const siblings = node.children_ids;
  const currentIndex = thread?.active_node_id === nodeId ? 0 : siblings.indexOf(thread?.active_node_id || '');

  return (
    <div className="flex items-center gap-1 text-xs">
      <button className="p-1 rounded hover:bg-accent">
        <ChevronLeft size={14} />
      </button>
      <span className="px-2 py-0.5 bg-secondary rounded">
        {currentIndex + 1} / {siblings.length}
      </span>
      <button className="p-1 rounded hover:bg-accent">
        <ChevronRight size={14} />
      </button>
    </div>
  );
}