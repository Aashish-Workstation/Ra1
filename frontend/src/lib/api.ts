const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api';

export const api = {
  chat: {
    process: async (message: string, threadId?: string) => {
      const res = await fetch(`${API_BASE}/chat/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, thread_id: threadId }),
      });
      return res.json();
    },
    stream: (threadId: string, onChunk: (chunk: string) => void, onError: (err: Error) => void) => {
      const eventSource = new EventSource(`${API_BASE}/chat/stream?thread_id=${threadId}`);
      eventSource.onmessage = (e) => onChunk(e.data);
      eventSource.onerror = (err) => {
        onError(err instanceof Error ? err : new Error('SSE error'));
        eventSource.close();
      };
      return eventSource;
    },
  },
  threads: {
    list: async () => {
      const res = await fetch(`${API_BASE}/threads`);
      return res.json();
    },
    create: async () => {
      const res = await fetch(`${API_BASE}/threads`, { method: 'POST' });
      return res.json();
    },
    get: async (id: string) => {
      const res = await fetch(`${API_BASE}/threads/${id}`);
      return res.json();
    },
    delete: async (id: string) => {
      await fetch(`${API_BASE}/threads/${id}`, { method: 'DELETE' });
    },
  },
  branches: {
    create: async (parentId: string, threadId: string) => {
      const res = await fetch(`${API_BASE}/branches`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parent_id: parentId, thread_id: threadId }),
      });
      return res.json();
    },
  },
  persona: {
    get: async () => {
      const res = await fetch(`${API_BASE}/persona/active`);
      return res.json();
    },
    update: async (blend: Record<string, number>) => {
      const res = await fetch(`${API_BASE}/persona`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ archetype_blend: blend }),
      });
      return res.json();
    },
  },
  memory: {
    list: async () => {
      const res = await fetch(`${API_BASE}/memory`);
      return res.json();
    },
    delete: async (id: string) => {
      await fetch(`${API_BASE}/memory/${id}`, { method: 'DELETE' });
    },
    lock: async (id: string, locked: boolean) => {
      await fetch(`${API_BASE}/memory/${id}/lock`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ locked }),
      });
    },
  },
  knowledge: {
    list: async () => {
      const res = await fetch(`${API_BASE}/knowledge`);
      return res.json();
    },
    upload: async (file: File) => {
      const formData = new FormData();
      formData.append('file', file);
      const res = await fetch(`${API_BASE}/knowledge`, {
        method: 'POST',
        body: formData,
      });
      return res.json();
    },
    delete: async (id: string) => {
      await fetch(`${API_BASE}/knowledge/${id}`, { method: 'DELETE' });
    },
  },
  notifications: {
    list: async () => {
      const res = await fetch(`${API_BASE}/notifications`);
      return res.json();
    },
  },
};