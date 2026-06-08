import { create } from 'zustand';
import { ChatState, ChatAction, ThreadTree, MessageNode } from '../types/tree';
import { v4 as uuidv4 } from 'uuid';

export const useChatStore = create<ChatState & ChatAction>((set, get) => ({
  threads: {},
  activeThreadId: null,
  sidebarOpen: true,
  inspectorTab: 'persona',

  sendMessage: (threadId, content) => {
    const thread = get().threads[threadId];
    if (!thread) return;
    
    const userNode: MessageNode = {
      node_id: uuidv4(),
      parent_id: thread.active_node_id,
      children_ids: [],
      user_id: 'current-user',
      content,
      role: 'user',
      status: 'sent',
      created_at: Date.now(),
      provisional: false,
    };

    const assistantNode: MessageNode = {
      node_id: uuidv4(),
      parent_id: userNode.node_id,
      children_ids: [],
      user_id: 'current-user',
      content: '',
      role: 'assistant',
      status: 'streaming',
      created_at: Date.now(),
      provisional: true,
    };

    const updatedNodes = {
      ...thread.nodes,
      [userNode.node_id]: userNode,
      [assistantNode.node_id]: assistantNode,
    };

    const updatedParent = get().threads[threadId];
    if (updatedParent) {
      updatedParent.nodes[thread.active_node_id].children_ids.push(userNode.node_id);
    }

    set((state) => ({
      threads: {
        ...state.threads,
        [threadId]: {
          ...thread,
          nodes: updatedNodes,
          active_node_id: assistantNode.node_id,
        },
      },
    }));
  },

  branchFromNode: (threadId, nodeId) => {
    const thread = get().threads[threadId];
    if (!thread) return '';
    
    const newNodeId = uuidv4();
    const originalNode = thread.nodes[nodeId];
    
    const newNode: MessageNode = {
      node_id: newNodeId,
      parent_id: originalNode.parent_id,
      children_ids: [...originalNode.children_ids],
      user_id: 'current-user',
      content: originalNode.content,
      role: originalNode.role,
      status: 'sent',
      created_at: Date.now(),
      provisional: true,
    };

    set((state) => ({
      threads: {
        ...state.threads,
        [threadId]: {
          ...state.threads[threadId],
          nodes: {
            ...state.threads[threadId].nodes,
            [newNodeId]: newNode,
          },
          active_node_id: newNodeId,
        },
      },
    }));

    return newNodeId;
  },

  switchBranch: (threadId, nodeId) => {
    set((state) => ({
      threads: {
        ...state.threads,
        [threadId]: {
          ...state.threads[threadId],
          active_node_id: nodeId,
        },
      },
    }));
  },

  commitBranch: (threadId, nodeId) => {
    set((state) => ({
      threads: {
        ...state.threads,
        [threadId]: {
          ...state.threads[threadId],
          nodes: {
            ...state.threads[threadId].nodes,
            [nodeId]: {
              ...state.threads[threadId].nodes[nodeId],
              provisional: false,
            },
          },
        },
      },
    }));
  },

  createThread: () => {
    const threadId = uuidv4();
    const rootNodeId = uuidv4();
    const rootNode: MessageNode = {
      node_id: rootNodeId,
      parent_id: null,
      children_ids: [],
      user_id: 'current-user',
      content: '',
      role: 'system',
      status: 'sent',
      created_at: Date.now(),
      provisional: false,
    };

    const newThread: ThreadTree = {
      thread_id: threadId,
      root_node_id: rootNodeId,
      active_node_id: rootNodeId,
      nodes: { [rootNodeId]: rootNode },
      branch_points: [],
    };

    set((state) => ({
      threads: { ...state.threads, [threadId]: newThread },
      activeThreadId: threadId,
    }));

    return threadId;
  },

  deleteThread: (threadId) => {
    const state = get();
    const remainingThreads = { ...state.threads };
    delete remainingThreads[threadId];
    
    let newActiveId = state.activeThreadId;
    if (state.activeThreadId === threadId) {
      const keys = Object.keys(remainingThreads);
      newActiveId = keys.length > 0 ? keys[0] : null;
    }

    set({ threads: remainingThreads, activeThreadId: newActiveId });
  },

  setActiveThread: (threadId) => {
    set({ activeThreadId: threadId });
  },

  setSidebarOpen: (open) => {
    set({ sidebarOpen: open });
  },

  setInspectorTab: (tab) => {
    set({ inspectorTab: tab });
  },
}));