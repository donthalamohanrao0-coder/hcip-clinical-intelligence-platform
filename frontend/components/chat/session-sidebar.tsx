'use client';

import { Plus, MessageSquare, Trash2 } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { ChatSession } from '@/lib/chat-types';
import { KNOWLEDGE_BASES } from '@/lib/types';

function formatRelativeTime(ts: number): string {
  const diffMs = Date.now() - ts;
  const min = Math.floor(diffMs / 60_000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day}d ago`;
  return new Date(ts).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

interface SessionSidebarProps {
  sessions:        ChatSession[];
  activeSessionId: string | null;
  onSelect:        (id: string) => void;
  onNewChat:       () => void;
  onDelete:        (id: string) => void;
}

export function SessionSidebar({
  sessions,
  activeSessionId,
  onSelect,
  onNewChat,
  onDelete,
}: SessionSidebarProps) {
  return (
    <aside className="flex h-full w-[240px] shrink-0 flex-col border-r bg-muted/20">
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="flex w-full items-center justify-center gap-2 rounded-lg border border-border bg-background px-3 py-2 text-sm font-medium text-foreground shadow-sm transition-colors hover:bg-accent"
        >
          <Plus className="h-4 w-4" />
          New chat
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-2 pb-3">
        {sessions.length === 0 ? (
          <p className="px-3 py-6 text-center text-xs text-muted-foreground/60">
            No conversations yet
          </p>
        ) : (
          <div className="space-y-0.5">
            {sessions.map((session) => {
              const active = session.id === activeSessionId;
              const kbLabel = KNOWLEDGE_BASES.find((kb) => kb.id === session.kbId)?.label;
              return (
                <div
                  key={session.id}
                  onClick={() => onSelect(session.id)}
                  className={cn(
                    'group flex cursor-pointer items-start gap-2 rounded-lg px-2.5 py-2 text-sm transition-colors',
                    active
                      ? 'bg-primary/10 text-foreground'
                      : 'text-muted-foreground hover:bg-accent hover:text-foreground',
                  )}
                >
                  <MessageSquare className="mt-0.5 h-3.5 w-3.5 shrink-0 opacity-60" />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium leading-tight">
                      {session.title}
                    </p>
                    <p className="mt-0.5 truncate text-[10px] text-muted-foreground/70">
                      {kbLabel ?? session.kbId} · {formatRelativeTime(session.updatedAt)}
                    </p>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(session.id);
                    }}
                    title="Delete chat"
                    className="shrink-0 rounded-md p-1 opacity-0 transition-opacity hover:bg-destructive/10 hover:text-destructive group-hover:opacity-100"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </aside>
  );
}
