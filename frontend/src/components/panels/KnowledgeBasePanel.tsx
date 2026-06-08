import { Upload, FileText, Trash2 } from 'lucide-react';
import { useChatStore } from '../../stores/treeStore';
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';

interface KnowledgeItem {
  item_id: string;
  content_type: string;
  content: any;
  tags: string[];
}

export default function KnowledgeBasePanel() {
  const { inspectorTab } = useChatStore();
  const [items, setItems] = useState<KnowledgeItem[]>([]);
  const [uploading, setUploading] = useState(false);

  useEffect(() => {
    if (inspectorTab === 'knowledge') {
      loadItems();
    }
  }, [inspectorTab]);

  const loadItems = async () => {
    try {
      const data = await api.knowledge.list();
      setItems(data);
    } catch (err) {
      console.error('Failed to load knowledge:', err);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    
    setUploading(true);
    try {
      await api.knowledge.upload(file);
      loadItems();
    } catch (err) {
      console.error('Failed to upload:', err);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const handleDelete = async (id: string) => {
    await api.knowledge.delete(id);
    setItems(items.filter(i => i.item_id !== id));
  };

  if (inspectorTab !== 'knowledge') return null;

  return (
    <div>
      <h3 className="font-semibold mb-4">Knowledge Base</h3>
      <div className="mb-4">
        <label className="flex items-center gap-2 px-3 py-2 bg-primary text-primary-foreground rounded-lg cursor-pointer hover:opacity-90 transition-opacity">
          <Upload size={16} />
          <span>{uploading ? 'Uploading...' : 'Upload Document'}</span>
          <input
            type="file"
            onChange={handleUpload}
            disabled={uploading}
            className="hidden"
          />
        </label>
      </div>
      <div className="space-y-2 max-h-80 overflow-y-auto">
        {items.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">No documents</div>
        ) : (
          items.map((item) => (
            <div
              key={item.item_id}
              className="p-3 bg-card rounded-lg border border-border flex items-center gap-2"
            >
              <FileText size={16} className="text-muted-foreground" />
              <div className="flex-1 truncate">
                <div className="text-sm">{item.content_type}</div>
                <div className="text-xs text-muted-foreground truncate">
                  {typeof item.content === 'string' ? item.content.slice(0, 50) : 'Structured content'}
                </div>
              </div>
              <button
                onClick={() => handleDelete(item.item_id)}
                className="p-1 rounded hover:bg-destructive hover:text-destructive-foreground"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  );
}