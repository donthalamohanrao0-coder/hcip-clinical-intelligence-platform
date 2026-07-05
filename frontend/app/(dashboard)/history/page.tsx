"use client";

import { useEffect, useState } from "react";
import { Header } from "@/components/layout/header";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  BookOpenCheck,
  ChevronDown,
  ChevronRight,
  Clock,
  Trash2,
  Zap,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { loadHistory, HISTORY_STORAGE_KEY } from "@/lib/history";
import type { HistoryEntry } from "@/lib/history";

function relativeTime(ts: number): string {
  const diff = Date.now() - ts;
  const mins = Math.floor(diff / 60_000);
  if (mins < 1)  return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24)  return `${hrs}h ago`;
  return new Date(ts).toLocaleDateString();
}

function reliabilityColor(score: number) {
  if (score >= 0.85) return "text-green-600 dark:text-green-400";
  if (score >= 0.70) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

function reliabilityLabel(score: number): string {
  if (score >= 0.85) return "High";
  if (score >= 0.70) return "Moderate";
  return "Low";
}

function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function HistoryCard({ entry, onDelete }: { entry: HistoryEntry; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const { query, result, timestamp } = entry;

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <button
            onClick={() => setOpen((o) => !o)}
            className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground transition-colors"
          >
            {open ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>

          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <p className="text-sm font-medium leading-snug line-clamp-2">{query}</p>
              <div className="flex shrink-0 items-center gap-1.5">
                <span className={cn("text-xs font-semibold", reliabilityColor(result.confidence_score))}>
                  {Math.round(result.confidence_score * 100)}%
                </span>
                <button
                  onClick={onDelete}
                  className="ml-1 text-muted-foreground hover:text-destructive transition-colors"
                  title="Remove from history"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>

            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Clock className="h-3 w-3" />
              <span>{relativeTime(timestamp)}</span>

              {/* Reliability badge */}
              <Badge
                variant="secondary"
                className={cn(
                  "text-[10px]",
                  result.confidence_score >= 0.85
                    ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                    : result.confidence_score >= 0.70
                    ? "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400"
                    : "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400",
                )}
              >
                {reliabilityLabel(result.confidence_score)} reliability
              </Badge>

              {/* Cache hit = instant response */}
              {result.cache_hit && (
                <Badge variant="outline" className="text-[10px] gap-1">
                  <Zap className="h-2.5 w-2.5" />
                  Instant response
                </Badge>
              )}

              {result.citations.length > 0 && (
                <Badge variant="secondary" className="text-[10px]">
                  {result.citations.length} source{result.citations.length !== 1 ? "s" : ""}
                </Badge>
              )}

              {result.safety_flags.length > 0 && (
                <Badge variant="destructive" className="text-[10px]">
                  {result.safety_flags.length} safety flag{result.safety_flags.length !== 1 ? "s" : ""}
                </Badge>
              )}

              {/* Response time — just show total, no agent breakdown */}
              <span className="ml-auto">
                Response time: {formatLatency(result.total_latency_ms)}
              </span>
            </div>

            {open && (
              <>
                <Separator className="my-3" />
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
                  {result.final_response}
                </p>

                {result.citations.length > 0 && (
                  <div className="mt-3 space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">Sources</p>
                    {result.citations.map((c) => (
                      <div
                        key={c.ref_number}
                        className="flex items-baseline gap-1.5 text-xs text-muted-foreground"
                      >
                        <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[9px] font-semibold text-primary">
                          {c.ref_number}
                        </span>
                        <span className="truncate">
                          {c.title ?? c.document_id}
                          {c.specialty ? ` · ${c.specialty}` : ""}
                        </span>
                        {c.is_external && c.url && (
                          <a
                            href={c.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-primary hover:underline shrink-0"
                          >
                            ↗
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function HistoryPage() {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);

  useEffect(() => {
    setEntries(loadHistory());
    const handler = () => setEntries(loadHistory());
    window.addEventListener("hcip_history_updated", handler);
    return () => window.removeEventListener("hcip_history_updated", handler);
  }, []);

  function deleteEntry(id: string) {
    const updated = entries.filter((e) => e.id !== id);
    setEntries(updated);
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(updated));
  }

  function clearAll() {
    setEntries([]);
    localStorage.removeItem(HISTORY_STORAGE_KEY);
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <Header
        title="Query History"
        description="Your past clinical questions — stored locally in this browser"
      />

      <ScrollArea className="flex-1">
        <div className="mx-auto max-w-4xl space-y-4 p-6">
          {entries.length > 0 && (
            <div className="flex items-center justify-between">
              <p className="text-sm text-muted-foreground">
                {entries.length} saved {entries.length === 1 ? "query" : "queries"}
              </p>
              <Button variant="outline" size="sm" onClick={clearAll}>
                <Trash2 className="mr-1.5 h-3.5 w-3.5" />
                Clear all
              </Button>
            </div>
          )}

          {entries.length === 0 && (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-20 text-center text-muted-foreground">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
                <BookOpenCheck className="h-6 w-6 opacity-40" />
              </div>
              <p className="font-medium text-foreground">No query history yet</p>
              <p className="mt-1 text-sm max-w-xs">
                Questions you ask in Clinical AI will appear here for easy reference.
              </p>
            </div>
          )}

          {entries.map((entry) => (
            <HistoryCard
              key={entry.id}
              entry={entry}
              onDelete={() => deleteEntry(entry.id)}
            />
          ))}
        </div>
      </ScrollArea>
    </div>
  );
}
