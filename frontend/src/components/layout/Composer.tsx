import { useState, useRef } from 'react';
import { Send, Paperclip, Mic, Clipboard } from 'lucide-react';
import { useChatStore } from '../../stores/treeStore';
import { api } from '../../lib/api';

export default function Composer() {
  const [message, setMessage] = useState('');
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { activeThreadId, sendMessage } = useChatStore();

  const handleSend = async () => {
    if (!message.trim() || !activeThreadId) return;
    const content = message.trim();
    setMessage('');
    sendMessage(activeThreadId, content);
    
    try {
      await api.chat.process(content, activeThreadId);
    } catch (err) {
      console.error('Failed to send message:', err);
    }
  };

  const handleFileSelect = async () => {
    const file = fileInputRef.current?.files?.[0];
    if (!file) return;
    
    setUploading(true);
    try {
      await api.knowledge.upload(file);
    } catch (err) {
      console.error('Failed to upload:', err);
    } finally {
      setUploading(false);
      fileInputRef.current!.value = '';
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    const text = e.clipboardData.getData('text');
    if (text) {
      setMessage((prev) => prev + text);
    }
  };

  return (
    <div className="p-4 border-t border-border">
      <div className="flex items-end gap-2">
        <div className="flex-1 relative">
          <textarea
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Type a message..."
            className="w-full px-3 py-2 pr-12 bg-input rounded-lg border border-border outline-none resize-none max-h-32"
            rows={1}
          />
          <div className="absolute right-2 bottom-2 flex gap-1">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="p-1 rounded hover:bg-accent transition-colors"
            >
              <Paperclip size={16} />
            </button>
            <input
              ref={fileInputRef}
              type="file"
              onChange={handleFileSelect}
              className="hidden"
            />
          </div>
        </div>
        <button
          onClick={handleSend}
          disabled={!message.trim() || uploading}
          className="p-2 rounded-lg bg-primary text-primary-foreground disabled:opacity-50 transition-opacity"
        >
          <Send size={18} />
        </button>
      </div>
    </div>
  );
}