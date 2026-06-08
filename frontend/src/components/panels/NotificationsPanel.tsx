import { Bell, AlertCircle, Info, CheckCircle, X } from 'lucide-react';
import { useChatStore } from '../../stores/treeStore';
import { useEffect, useState } from 'react';
import { api } from '../../lib/api';

interface Notification {
  id: string;
  priority: 'P0_BLOCK' | 'P1_URGENT' | 'P2_INFORM' | 'P3_NOTICE' | 'P_SILENT';
  title: string;
  message: string;
  read: boolean;
  created_at: string;
}

const priorityConfig = {
  P0_BLOCK: { icon: AlertCircle, color: 'text-red-500', label: 'P0' },
  P1_URGENT: { icon: AlertCircle, color: 'text-orange-500', label: 'P1' },
  P2_INFORM: { icon: Info, color: 'text-blue-500', label: 'P2' },
  P3_NOTICE: { icon: CheckCircle, color: 'text-green-500', label: 'P3' },
  P_SILENT: { icon: Bell, color: 'text-gray-500', label: 'Silent' },
};

export default function NotificationsPanel() {
  const { inspectorTab } = useChatStore();
  const [notifications, setNotifications] = useState<Notification[]>([]);

  useEffect(() => {
    if (inspectorTab === 'notifications') {
      loadNotifications();
    }
  }, [inspectorTab]);

  const loadNotifications = async () => {
    try {
      const data = await api.notifications.list();
      setNotifications(data);
    } catch (err) {
      console.error('Failed to load notifications:', err);
    }
  };

  const handleDismiss = (id: string) => {
    setNotifications(notifications.filter(n => n.id !== id));
  };

  if (inspectorTab !== 'notifications') return null;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-semibold">Notifications</h3>
        <div className="text-xs text-muted-foreground">
          Model: <span className="font-medium">gpt-4o</span>
        </div>
      </div>
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {notifications.length === 0 ? (
          <div className="text-center py-8 text-muted-foreground">No notifications</div>
        ) : (
          notifications.map((n) => {
            const config = priorityConfig[n.priority];
            const Icon = config.icon;
            return (
              <div
                key={n.id}
                className={`p-3 bg-card rounded-lg border ${
                  n.priority === 'P0_BLOCK' ? 'border-red-500' : 'border-border'
                } ${!n.read ? 'ring-1 ring-primary' : ''}`}
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-2">
                    <Icon size={16} className={config.color} />
                    <div>
                      <div className="text-sm font-medium flex items-center gap-2">
                        {n.title}
                        <span className={`text-${config.color} text-xs`}>{config.label}</span>
                      </div>
                      <div className="text-xs text-muted-foreground mt-1">{n.message}</div>
                    </div>
                  </div>
                  <button
                    onClick={() => handleDismiss(n.id)}
                    className="p-1 rounded hover:bg-accent"
                  >
                    <X size={14} />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}