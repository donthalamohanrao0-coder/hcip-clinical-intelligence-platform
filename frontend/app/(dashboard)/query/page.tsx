'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import {
  Heart,
  Stethoscope,
  AlertTriangle,
  BookOpen,
  ChevronDown,
  ExternalLink,
  ArrowUp,
  Square,
  ChevronDown as ChevronDownIcon,
} from 'lucide-react';
import { useAuth } from '@/context/auth-context';
import { streamQuery, type StreamEvent, type QueryMeta } from '@/lib/api';
import { saveToHistory } from '@/lib/history';
import { KNOWLEDGE_BASES, type QueryResult } from '@/lib/types';
import { cn } from '@/lib/utils';
import type { ChatMessage, ChatSource, ChatSession } from '@/lib/chat-types';
import { loadSessions, saveSessions, createSession, deriveTitle } from '@/lib/chat-sessions';
import { SessionSidebar } from '@/components/chat/session-sidebar';

// ─── Constants ───────────────────────────────────────────────────────────────

const SUGGESTIONS = [
  'What are the first-line treatments for type 2 diabetes?',
  'Dosing guidelines for metformin in patients with CKD?',
  'Signs and symptoms of acute heart failure?',
  'Drug interactions with warfarin I should watch for?',
];

// ─── Sub-components ──────────────────────────────────────────────────────────

function renderResponse(text: string) {
  const parts = text.split(/(\[\d+\])/g);
  return parts.map((part, i) => {
    const match = part.match(/^\[(\d+)\]$/);
    if (match) {
      return (
        <sup
          key={i}
          className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-primary/10 text-[9px] font-semibold text-primary mx-0.5 cursor-default select-none"
        >
          {match[1]}
        </sup>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

function SourcesPanel({ sources }: { sources: ChatSource[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3">
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <BookOpen className="h-3.5 w-3.5" />
        <span>
          {sources.length} source{sources.length !== 1 ? 's' : ''}
        </span>
        <ChevronDown
          className={cn('h-3 w-3 transition-transform', open && 'rotate-180')}
        />
      </button>

      {open && (
        <div className="mt-2 grid gap-1.5">
          {sources.map((source) => (
            <div
              key={source.number}
              className="flex items-start gap-2 rounded-lg border border-border/50 bg-muted/30 px-3 py-2"
            >
              <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-semibold text-primary">
                {source.number}
              </span>
              <div className="min-w-0 flex-1">
                <p className="text-xs font-medium text-foreground capitalize">
                  {source.title || 'Clinical Reference'}
                </p>
                {source.specialty && (
                  <p className="text-[11px] text-muted-foreground">
                    {source.specialty}
                  </p>
                )}
              </div>
              {source.isExternal && source.url && (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="shrink-0 text-primary hover:text-primary/70 transition-colors"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                </a>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StageIndicator({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-2 h-5">
      <div className="flex gap-1 items-center">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-1.5 w-1.5 rounded-full bg-primary/50 animate-bounce"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
      <span className="text-sm text-muted-foreground animate-pulse">{label}</span>
    </div>
  );
}

function StreamingCursor() {
  return (
    <span
      aria-hidden
      className="inline-block w-[2px] h-[1em] translate-y-[2px] bg-primary/70 ml-0.5 animate-pulse"
    />
  );
}

function UserBubble({ message }: { message: ChatMessage }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[70%] rounded-2xl rounded-tr-sm bg-primary px-4 py-3 text-sm text-primary-foreground leading-relaxed">
        {message.content}
      </div>
    </div>
  );
}

function AssistantBubble({ message }: { message: ChatMessage }) {
  const confidence = message.confidence ?? 0;

  if (message.error) {
    return (
      <div className="flex gap-3 items-start">
        <div className="h-8 w-8 rounded-full bg-destructive/10 flex items-center justify-center shrink-0">
          <AlertTriangle className="h-4 w-4 text-destructive" />
        </div>
        <div className="rounded-2xl rounded-tl-sm border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive max-w-[85%]">
          {message.error}
        </div>
      </div>
    );
  }

  const showStage = message.isStreaming && !message.content;

  return (
    <div className="flex gap-3 items-start">
      <div className="h-8 w-8 rounded-full bg-primary/10 flex items-center justify-center shrink-0">
        <Heart className="h-4 w-4 text-primary" />
      </div>

      <div className="flex-1 min-w-0">
        {showStage ? (
          <StageIndicator label={message.stageLabel || 'Thinking'} />
        ) : (
          <div className="prose prose-sm max-w-none text-foreground leading-relaxed text-sm">
            {renderResponse(message.content)}
            {message.isStreaming && <StreamingCursor />}
          </div>
        )}

        {!message.isStreaming && message.isEscalated && (
          <div className="mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/30 px-3 py-2.5 text-xs text-amber-800 dark:text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0 mt-0.5 text-amber-500" />
            <p>{message.safetyNote}</p>
          </div>
        )}

        {!message.isStreaming && message.sources && message.sources.length > 0 && (
          <SourcesPanel sources={message.sources} />
        )}

        {!message.isStreaming && (
          <div className="mt-2 flex items-center gap-3 text-[11px] text-muted-foreground/60">
            {message.confidence !== undefined && message.confidence > 0 && (
              <span className="flex items-center gap-1">
                <span
                  className={
                    confidence > 0.7
                      ? 'text-green-500'
                      : confidence > 0.4
                      ? 'text-amber-500'
                      : 'text-red-400'
                  }
                >
                  ●
                </span>
                {Math.round(message.confidence * 100)}% reliable
              </span>
            )}
            {message.latencyMs !== undefined && (
              <span>
                {message.latencyMs < 1000
                  ? `${Math.round(message.latencyMs)}ms`
                  : `${(message.latencyMs / 1000).toFixed(1)}s`}
              </span>
            )}
            {message.cacheHit && <span>· Instant</span>}
          </div>
        )}
      </div>
    </div>
  );
}

function mapCitationsToSources(citations: QueryResult['citations']): ChatSource[] {
  return citations.map((c) => ({
    number:     c.ref_number,
    title:      c.document_type
      ? `${c.document_type.replace(/_/g, ' ')}${c.specialty ? ` · ${c.specialty}` : ''}`.trim()
      : c.is_external
      ? c.title || 'External Reference'
      : 'Clinical Reference',
    isExternal: c.is_external,
    url:        c.url,
    specialty:  c.specialty,
  }));
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export default function QueryPage() {
  const { user, token } = useAuth();

  const allowedKbIds = user?.allowed_kb_ids ?? KNOWLEDGE_BASES.map((k) => k.id);
  const allowedKbs   = KNOWLEDGE_BASES.filter((kb) => allowedKbIds.includes(kb.id));
  const defaultKbId  =
    (process.env.NEXT_PUBLIC_DEFAULT_KB_ID as string | undefined) ??
    allowedKbs[0]?.id ??
    KNOWLEDGE_BASES[0].id;

  const [activeKbId,      setActiveKbId]      = useState(defaultKbId);
  const [sessions,        setSessions]        = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages,        setMessages]        = useState<ChatMessage[]>([]);
  const [input,           setInput]           = useState('');
  const [isLoading,       setIsLoading]       = useState(false);

  const textareaRef        = useRef<HTMLTextAreaElement>(null);
  const scrollAnchor       = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const metaRef            = useRef<QueryMeta | null>(null);

  // Load (or migrate) conversations from localStorage once on mount.
  useEffect(() => {
    const loaded = loadSessions();
    if (loaded.length > 0) {
      setSessions(loaded);
      setActiveSessionId(loaded[0].id);
      setMessages(loaded[0].messages);
      setActiveKbId(loaded[0].kbId);
    } else {
      const fresh = createSession(defaultKbId);
      setSessions([fresh]);
      setActiveSessionId(fresh.id);
      saveSessions([fresh]);
    }
    // Intentionally run once — session switching is handled by explicit handlers below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto-scroll
  useEffect(() => {
    scrollAnchor.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isLoading]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  // Writes the given message list into the active session (retitling it from
  // the first user message if it's still an untitled "New chat") and persists.
  const persistMessagesToSession = useCallback(
    (msgs: ChatMessage[]) => {
      setSessions((prev) => {
        const idx = prev.findIndex((s) => s.id === activeSessionId);
        if (idx === -1) return prev;

        const firstUser = msgs.find((m) => m.role === 'user');
        const updated: ChatSession = {
          ...prev[idx],
          messages:  msgs,
          updatedAt: Date.now(),
          title:     prev[idx].title === 'New chat' && firstUser
            ? deriveTitle(firstUser.content)
            : prev[idx].title,
        };

        const next = [...prev];
        next[idx] = updated;
        next.sort((a, b) => b.updatedAt - a.updatedAt);
        saveSessions(next);
        return next;
      });
    },
    [activeSessionId],
  );

  // Applies an update to the currently-streaming assistant message (always
  // the last message in the array while isLoading is true).
  const patchStreamingMessage = useCallback(
    (patch: Partial<ChatMessage> | ((m: ChatMessage) => Partial<ChatMessage>)) => {
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const last = prev[prev.length - 1];
        const delta = typeof patch === 'function' ? patch(last) : patch;
        return [...prev.slice(0, -1), { ...last, ...delta }];
      });
    },
    [],
  );

  // Persists whatever the latest committed message state is, without
  // triggering an extra re-render (the updater returns the same reference).
  const persistCurrent = useCallback(() => {
    setMessages((prevMsgs) => {
      persistMessagesToSession(prevMsgs);
      return prevMsgs;
    });
  }, [persistMessagesToSession]);

  const handleNewChat = useCallback(() => {
    abortControllerRef.current?.abort();
    const fresh = createSession(activeKbId);
    setSessions((prev) => {
      const next = [fresh, ...prev];
      saveSessions(next);
      return next;
    });
    setActiveSessionId(fresh.id);
    setMessages([]);
    setInput('');
  }, [activeKbId]);

  const handleSelectSession = useCallback(
    (id: string) => {
      if (id === activeSessionId) return;
      abortControllerRef.current?.abort();
      const session = sessions.find((s) => s.id === id);
      if (!session) return;
      setActiveSessionId(id);
      setMessages(session.messages);
      setActiveKbId(session.kbId);
      setInput('');
    },
    [activeSessionId, sessions],
  );

  const handleDeleteSession = useCallback(
    (id: string) => {
      const next = sessions.filter((s) => s.id !== id);

      if (id !== activeSessionId) {
        setSessions(next);
        saveSessions(next);
        return;
      }

      abortControllerRef.current?.abort();
      if (next.length > 0) {
        setActiveSessionId(next[0].id);
        setMessages(next[0].messages);
        setActiveKbId(next[0].kbId);
        setSessions(next);
        saveSessions(next);
      } else {
        const fresh = createSession(defaultKbId);
        setActiveSessionId(fresh.id);
        setMessages([]);
        setActiveKbId(fresh.kbId);
        setSessions([fresh]);
        saveSessions([fresh]);
      }
    },
    [sessions, activeSessionId, defaultKbId],
  );

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;

    setInput('');

    const userMsg: ChatMessage = {
      id:        `u-${Date.now()}`,
      role:      'user',
      content:   text,
      timestamp: new Date(),
    };
    const assistantMsg: ChatMessage = {
      id:          `a-${Date.now()}`,
      role:        'assistant',
      content:     '',
      timestamp:   new Date(),
      isStreaming: true,
      stageLabel:  'Understanding your question',
    };

    const next = [...messages, userMsg, assistantMsg];
    setMessages(next);
    persistMessagesToSession(next);
    setIsLoading(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    let fullText = '';
    metaRef.current = null;

    try {
      await streamQuery(
        {
          query:             text,
          knowledge_base_id: activeKbId,
          organization_id:   user?.organization_id,
          token:             token ?? undefined,
        },
        (event: StreamEvent) => {
          if (event.type === 'stage') {
            patchStreamingMessage({ stageLabel: event.label });
          } else if (event.type === 'token') {
            fullText += event.text;
            patchStreamingMessage({ content: fullText });
          } else if (event.type === 'meta') {
            metaRef.current = event;
          } else if (event.type === 'error') {
            patchStreamingMessage({ error: event.message, isStreaming: false });
          }
          // 'done' has no payload — finalization happens after the loop below.
        },
        controller.signal,
      );

      const meta = metaRef.current as QueryMeta | null;
      if (meta) {
        const finalized: Partial<ChatMessage> = {
          isStreaming: false,
          stageLabel:  undefined,
          sources:     mapCitationsToSources(meta.citations),
          confidence:  meta.confidence_score,
          isEscalated: meta.requires_escalation,
          safetyNote:  meta.requires_escalation
            ? meta.escalation_reason || 'This response requires clinical review before application.'
            : undefined,
          latencyMs:   meta.total_latency_ms,
          cacheHit:    meta.cache_hit,
        };
        patchStreamingMessage(finalized);

        const result: QueryResult = { query_text: text, final_response: fullText, ...meta };
        saveToHistory(text, result);
      } else {
        // Stream ended without a meta event (e.g. stopped early) — just
        // freeze whatever text arrived so far.
        patchStreamingMessage({ isStreaming: false, stageLabel: undefined });
      }
      persistCurrent();
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        patchStreamingMessage({ isStreaming: false, stageLabel: undefined });
      } else {
        patchStreamingMessage({
          isStreaming: false,
          stageLabel:  undefined,
          error:       err instanceof Error ? err.message : 'Something went wrong. Please try again.',
        });
      }
      persistCurrent();
    } finally {
      abortControllerRef.current = null;
      setIsLoading(false);
    }
  }, [input, isLoading, messages, activeKbId, user, token, persistMessagesToSession, persistCurrent, patchStreamingMessage]);

  const handleStop = useCallback(() => {
    abortControllerRef.current?.abort();
  }, []);

  // Changing the library mid-conversation retargets the *current* session's
  // future queries — it doesn't create a new chat or clear history.
  const handleKbChange = useCallback(
    (id: string) => {
      setActiveKbId(id);
      setSessions((prev) => {
        const next = prev.map((s) => (s.id === activeSessionId ? { ...s, kbId: id } : s));
        saveSessions(next);
        return next;
      });
    },
    [activeSessionId],
  );

  const activeKb = allowedKbs.find((kb) => kb.id === activeKbId);

  return (
    <div className="flex h-full overflow-hidden">
      <SessionSidebar
        sessions={sessions}
        activeSessionId={activeSessionId}
        onSelect={handleSelectSession}
        onNewChat={handleNewChat}
        onDelete={handleDeleteSession}
      />

      <div className="flex h-full flex-1 flex-col overflow-hidden">
      {/* ── Top bar ── */}
      <div className="flex shrink-0 items-center justify-between border-b bg-background px-4 py-3 gap-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-primary/10">
            <Stethoscope className="h-3.5 w-3.5 text-primary" />
          </div>
          <span className="font-semibold text-sm text-foreground">Clinical AI</span>
        </div>

        <div className="flex items-center gap-2">
          {/* Library selector */}
          <div className="relative">
            <select
              value={activeKbId}
              onChange={(e) => handleKbChange(e.target.value)}
              className="appearance-none rounded-lg border border-border bg-background pl-3 pr-8 py-1.5 text-xs font-medium text-foreground focus:outline-none focus:ring-1 focus:ring-primary/30 cursor-pointer"
            >
              {allowedKbs.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.label}
                </option>
              ))}
            </select>
            <ChevronDownIcon className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground" />
          </div>
        </div>
      </div>

      {/* ── Messages area ── */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-4 py-6">
          {messages.length === 0 && !isLoading ? (
            /* ── Empty state ── */
            <div className="flex flex-col items-center justify-center gap-8 py-12 px-4">
              <div className="text-center space-y-2">
                <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10">
                  <Stethoscope className="h-7 w-7 text-primary" />
                </div>
                <h2 className="text-xl font-semibold text-foreground">
                  Clinical AI Assistant
                </h2>
                <p className="text-sm text-muted-foreground max-w-sm mx-auto">
                  Ask any clinical question. I&apos;ll search your{' '}
                  <span className="font-medium text-foreground">
                    {activeKb?.label ?? 'library'}
                  </span>{' '}
                  and provide evidence-based answers with sources.
                </p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 w-full max-w-2xl">
                {SUGGESTIONS.map((s) => (
                  <button
                    key={s}
                    onClick={() => setInput(s)}
                    className="text-left rounded-xl border border-border hover:border-primary/30 hover:bg-primary/5 px-4 py-3 text-sm text-muted-foreground transition-all duration-150"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            /* ── Conversation ── */
            <div className="space-y-6">
              {messages.map((message) =>
                message.role === 'user' ? (
                  <UserBubble key={message.id} message={message} />
                ) : (
                  <AssistantBubble key={message.id} message={message} />
                ),
              )}
              <div ref={scrollAnchor} />
            </div>
          )}
        </div>
      </div>

      {/* ── Input bar ── */}
      <div className="shrink-0 border-t bg-background px-4 py-4">
        <div className="mx-auto max-w-3xl">
          <div className="relative flex items-end gap-2 rounded-2xl border border-border bg-background shadow-sm focus-within:border-primary/50 focus-within:ring-1 focus-within:ring-primary/20 transition-all">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                  e.preventDefault();
                  handleSend();
                }
              }}
              placeholder="Ask a clinical question..."
              rows={1}
              className="flex-1 resize-none bg-transparent px-4 py-3.5 text-sm outline-none placeholder:text-muted-foreground/50 overflow-y-auto leading-relaxed"
              style={{ maxHeight: '160px' }}
              disabled={isLoading}
            />
            <button
              onClick={isLoading ? handleStop : handleSend}
              disabled={!isLoading && !input.trim()}
              className={cn(
                'mb-2 mr-2 flex h-8 w-8 items-center justify-center rounded-lg transition-opacity disabled:opacity-30 shrink-0',
                isLoading
                  ? 'bg-foreground/80 text-background hover:bg-foreground'
                  : 'bg-primary text-primary-foreground hover:bg-primary/90',
              )}
              title={isLoading ? 'Stop generating' : 'Send'}
            >
              {isLoading ? (
                <Square className="h-3.5 w-3.5 fill-current" />
              ) : (
                <ArrowUp className="h-4 w-4" />
              )}
            </button>
          </div>
          <p className="mt-2 text-center text-[11px] text-muted-foreground/40">
            {isLoading
              ? 'Generating — click stop to cancel'
              : 'Press Ctrl+Enter to send · Responses are AI-generated and should be reviewed by a licensed clinician'}
          </p>
        </div>
      </div>
      </div>
    </div>
  );
}
