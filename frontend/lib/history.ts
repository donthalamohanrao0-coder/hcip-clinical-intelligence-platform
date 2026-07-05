import type { QueryResult } from "./types";

export const HISTORY_STORAGE_KEY = "hcip_query_history";
export const HISTORY_MAX_ENTRIES = 50;

export interface HistoryEntry {
  id:        string;
  query:     string;
  result:    QueryResult;
  timestamp: number;
}

export function loadHistory(): HistoryEntry[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(localStorage.getItem(HISTORY_STORAGE_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function saveToHistory(query: string, result: QueryResult): void {
  if (typeof window === "undefined") return;
  try {
    const prev = loadHistory();
    const entry: HistoryEntry = {
      id:        `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      query,
      result,
      timestamp: Date.now(),
    };
    localStorage.setItem(
      HISTORY_STORAGE_KEY,
      JSON.stringify([entry, ...prev].slice(0, HISTORY_MAX_ENTRIES)),
    );
    window.dispatchEvent(new Event("hcip_history_updated"));
  } catch {}
}
