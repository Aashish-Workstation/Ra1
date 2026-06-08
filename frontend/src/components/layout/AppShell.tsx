import { ReactNode } from 'react';
import Sidebar from './Sidebar';
import { useChatStore } from '../stores/treeStore';

type AppShellProps = {
  children: ReactNode;
};

export default function AppShell({ children }: AppShellProps) {
  const { sidebarOpen, setSidebarOpen } = useChatStore();

  return (
    <div className="flex h-screen w-screen bg-background">
      <Sidebar open={sidebarOpen} onToggle={setSidebarOpen} />
      <div className="flex-1 flex flex-col overflow-hidden">
        {children}
      </div>
    </div>
  );
}