export type MessageNode = {
  node_id: string;
  parent_id: string | null;
  children_ids: string[];
  user_id: string;
  content: string;
  role: 'user' | 'assistant' | 'system';
  status: 'sending' | 'sent' | 'streaming' | 'failed';
  created_at: number;
  provisional: boolean;
  metadata?: {
    model_id?: string;
    tokens?: number;
    latency_ms?: number;
  };
};

export type ThreadTree = {
  thread_id: string;
  root_node_id: string;
  active_node_id: string;
  nodes: Record<string, MessageNode>;
  branch_points: string[];
};

export type ChatState = {
  threads: Record<string, ThreadTree>;
  activeThreadId: string | null;
  sidebarOpen: boolean;
  inspectorTab: 'persona' | 'memory' | 'knowledge' | 'notifications';
};

export type ChatAction = {
  sendMessage: (threadId: string, content: string) => void;
  branchFromNode: (threadId: string, nodeId: string) => string;
  switchBranch: (threadId: string, nodeId: string) => void;
  commitBranch: (threadId: string, nodeId: string) => void;
  createThread: () => string;
  deleteThread: (threadId: string) => void;
  setActiveThread: (threadId: string) => void;
  setSidebarOpen: (open: boolean) => void;
  setInspectorTab: (tab: 'persona' | 'memory' | 'knowledge' | 'notifications') => void;
};