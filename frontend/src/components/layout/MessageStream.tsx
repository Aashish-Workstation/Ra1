import { useMemo } from 'react';
import { useChatStore } from '../../stores/treeStore';
import { BranchSelector } from '../branches/BranchSelector';

export default function MessageStream() {
  const { threads, activeThreadId } = useChatStore();
  const thread = activeThreadId ? threads[activeThreadId] : null;

  if (!thread) {
    return (
      <div className="flex-1 flex items-center justify-center text-muted-foreground">
        Select a thread or create a new one
      </div>
    );
  }

  const nodeOrder = useMemo(() => {
    const visited = new Set<string>();
    const order: string[] = [];
    
    const traverse = (nodeId: string) => {
      if (visited.has(nodeId)) return;
      visited.add(nodeId);
      const node = thread.nodes[nodeId];
      if (node && node.role !== 'system') {
        order.push(nodeId);
      }
      node?.children_ids.forEach(traverse);
    };
    
    traverse(thread.root_node_id);
    return order;
  }, [thread]);

  return (
    <div className="flex-1 overflow-y-auto p-4 space-y-4">
      {nodeOrder.length === 0 ? (
        <div className="text-center text-muted-foreground pt-8">
          <p>Start the conversation by sending a message</p>
        </div>
      ) : (
        nodeOrder.map((nodeId) => {
          const node = thread.nodes[nodeId];
          const isUser = node.role === 'user';
          
          return (
            <div key={nodeId} className={`flex ${isUser ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-xs px-4 py-2 rounded-lg ${
                isUser ? 'bg-primary text-primary-foreground' : 'bg-card'
              }`}>
                <div className="text-sm">{node.content}</div>
                {!isUser && node.status === 'streaming' && (
                  <div className="flex items-center gap-1 mt-1">
                    <span className="text-xs text-muted-foreground">Streaming...</span>
                  </div>
                )}
              </div>
            </div>
          );
        })
      )}
    </div>
  );
}