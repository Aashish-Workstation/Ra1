import { Trash2, Lock, Unlock } from 'lucide-react';
import { useChatStore } from '../../stores/treeStore';
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';

interface MemoryRecord {
  entity_id: string;
  entity_type: string;
  attribute: string;
  value: any;
  confidence: number;
  lock_status: boolean;
}

export default function MemoryPalacePanel() {
  const { inspectorTab } = useChatStore();
  const [records, setRecords] = useState<MemoryRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (inspectorTab === 'memory') {
      loadRecords();
    }
  }, [inspectorTab]);

  const loadRecords = async () => {
    setLoading(true);
    try {
      const data = await api.memory.list();
      setRecords(data);
    } catch (err) {
      console.error('Failed to load memory:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (id: string) => {
    await api.memory.delete(id);
    setRecords(records.filter(r => r.entity_id !== id));
  };

  const handleLock = async (id: string, locked: boolean) => {
    await api.memory.lock(id, locked);
    setRecords(records.map(r => 
      r.entity_id === id ? { ...r, lock_status: locked } : r
    ));
  };

  if (inspectorTab !== 'memory') return null;

  return (
    <div>
      <h3 className="font-semibold mb-4">Memory Palace</h3>
      {loading ? (
        <div className="text-center py-8 text-muted-foreground">Loading...</div>
      ) : (
        <div className="grid grid-cols-1 gap-2 max-h-96 overflow-y-auto">
          {records.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">No memory records</div>
          ) : (
            records.map((record) => (
              <div
                key={record.entity_id}
                className="p-3 bg-card rounded-lg border border-border"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <div className="text-sm font-medium">{record.attribute}</div>
                    <div className="text-xs text-muted-foreground truncate">
                      {JSON.stringify(record.value)}
                    </div>
                    <div className="text-xs mt-1">
                      Confidence: {(record.confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div className="flex gap-1">
                    <button
                      onClick={() => handleLock(record.entity_id, !record.lock_status)}
                      className="p-1 rounded hover:bg-accent"
                    >
                      {record.lock_status ? (
                        <Unlock size={14} />
                      ) : (
                        <Lock size={14} />
                      )}
                    </button>
                    <button
                      onClick={() => handleDelete(record.entity_id)}
                      className="p-1 rounded hover:bg-destructive hover:text-destructive-foreground"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}