/**
 * Multi-conversation chat storage — the "New chat" / conversation history
 * feature. Sessions are stored as one JSON blob in localStorage, newest
 * first by `updatedAt`.
 *
 * One-time migration: earlier versions of this app kept a single thread per
 * knowledge base under `hcip_chat_<kbId>`. On first load we fold any of
 * those into proper sessions so existing conversations aren't lost.
 */

import type { ChatMessage, ChatSession } from './chat-types';
import { KNOWLEDGE_BASES } from './types';

const SESSIONS_KEY  = 'hcip_chat_sessions_v1';
const MIGRATED_FLAG = 'hcip_chat_sessions_migrated_v1';

function reviveMessages(messages: ChatMessage[]): ChatMessage[] {
  return messages.map((m) => ({ ...m, timestamp: new Date(m.timestamp) }));
}

function migrateLegacyThreads(): ChatSession[] {
  const migrated: ChatSession[] = [];

  for (const kb of KNOWLEDGE_BASES) {
    const legacyKey = `hcip_chat_${kb.id}`;
    try {
      const raw = localStorage.getItem(legacyKey);
      if (!raw) continue;

      const messages = reviveMessages(JSON.parse(raw) as ChatMessage[]);
      if (messages.length === 0) continue;

      const firstUser = messages.find((m) => m.role === 'user');
      const createdAt = messages[0]?.timestamp.getTime() ?? Date.now();
      const updatedAt = messages[messages.length - 1]?.timestamp.getTime() ?? createdAt;

      migrated.push({
        id:        `session-${kb.id}-${createdAt}`,
        title:     firstUser ? deriveTitle(firstUser.content) : 'Untitled chat',
        kbId:      kb.id,
        messages,
        createdAt,
        updatedAt,
      });
    } catch {
      // ignore malformed legacy entry
    } finally {
      localStorage.removeItem(legacyKey);
    }
  }

  return migrated.sort((a, b) => b.updatedAt - a.updatedAt);
}

export function deriveTitle(text: string): string {
  const clean = text.trim().replace(/\s+/g, ' ');
  return clean.length > 48 ? `${clean.slice(0, 48)}…` : clean || 'New chat';
}

export function loadSessions(): ChatSession[] {
  if (typeof window === 'undefined') return [];

  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as ChatSession[];
      return parsed.map((s) => ({ ...s, messages: reviveMessages(s.messages) }));
    }

    if (!localStorage.getItem(MIGRATED_FLAG)) {
      const migrated = migrateLegacyThreads();
      localStorage.setItem(MIGRATED_FLAG, '1');
      if (migrated.length > 0) {
        saveSessions(migrated);
      }
      return migrated;
    }
  } catch {
    /* fall through to empty */
  }

  return [];
}

export function saveSessions(sessions: ChatSession[]): void {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
  } catch {
    /* storage full or unavailable — ignore */
  }
}

export function createSession(kbId: string): ChatSession {
  const now = Date.now();
  return {
    id:        `session-${now}-${Math.random().toString(36).slice(2, 8)}`,
    title:     'New chat',
    kbId,
    messages:  [],
    createdAt: now,
    updatedAt: now,
  };
}
