import { useEffect, useState, useRef } from 'react';
import { api } from '../lib/api';

export const useStreaming = (threadId: string | null) => {
  const [stream, setStream] = useState<string>('');
  const [isStreaming, setIsStreaming] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!threadId) return;

    setIsStreaming(true);
    setStream('');

    const es = api.chat.stream(
      threadId,
      (chunk) => setStream((prev) => prev + chunk),
      (err) => {
        console.error('Streaming error:', err);
        setIsStreaming(false);
      }
    );
    
    eventSourceRef.current = es;

    return () => {
      es.close();
      setIsStreaming(false);
    };
  }, [threadId]);

  return { stream, isStreaming };
};