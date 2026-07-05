/** Shared chat types — used by the Query page and the chat-sessions store. */

export interface ChatSource {
  number:      number;
  title:       string;
  isExternal?: boolean;
  url?:        string;
  specialty?:  string;
}

export interface ChatMessage {
  id:           string;
  role:         'user' | 'assistant';
  content:      string;
  timestamp:    Date;
  sources?:     ChatSource[];
  confidence?:  number;
  isEscalated?: boolean;
  safetyNote?:  string;
  latencyMs?:   number;
  cacheHit?:    boolean;
  error?:       string;
  isStreaming?: boolean;
  stageLabel?:  string;
}

export interface ChatSession {
  id:        string;
  title:     string;
  kbId:      string;
  messages:  ChatMessage[];
  createdAt: number;
  updatedAt: number;
}
