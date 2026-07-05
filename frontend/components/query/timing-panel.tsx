"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, Timer } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { formatMs } from "@/lib/utils";

interface TimingPanelProps {
  totalMs:      number;
  agentTimings: Record<string, number>;
  cacheHit:     boolean;
}

const AGENT_LABELS: Record<string, string> = {
  "planner.classify_ms":   "Planner · Classify",
  "planner.embed_ms":      "Planner · Embed",
  "planner.cache_ms":      "Planner · Cache check",
  "retrieval.qdrant_ms":   "Retriever · Qdrant",
  "retrieval.es_ms":       "Retriever · Elasticsearch",
  "retrieval.neo4j_ms":    "Retriever · Neo4j",
  "retrieval.pubmed_ms":   "Retriever · PubMed",
  "retrieval.rerank_ms":   "Retriever · Re-rank",
  "verifier.score_ms":     "Verifier · Citation score",
  "verifier.contradict_ms":"Verifier · Contradictions",
  "safety.detect_ms":      "Safety · Risk detect",
  "safety.escalate_ms":    "Safety · Escalation",
  "response.synthesize_ms":"Response · Synthesis",
  "response.citations_ms": "Response · Citations",
  "response.confidence_ms":"Response · Confidence",
};

export function TimingPanel({ totalMs, agentTimings, cacheHit }: TimingPanelProps) {
  const [open, setOpen] = useState(false);

  const entries = Object.entries(agentTimings)
    .map(([k, v]) => ({ key: k, label: AGENT_LABELS[k] ?? k, ms: v }))
    .sort((a, b) => b.ms - a.ms);

  return (
    <div className="rounded-lg border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-4 py-3 text-sm text-muted-foreground hover:text-foreground"
      >
        <Timer className="h-4 w-4 shrink-0" />
        <span className="flex-1 text-left font-medium">Pipeline timing</span>
        <Badge variant="secondary">{formatMs(totalMs)}</Badge>
        {cacheHit && <Badge variant="success">cache hit</Badge>}
        {open ? (
          <ChevronDown className="h-4 w-4" />
        ) : (
          <ChevronRight className="h-4 w-4" />
        )}
      </button>

      {open && entries.length > 0 && (
        <div className="border-t px-4 pb-3 pt-2">
          <div className="space-y-1.5">
            {entries.map(({ key, label, ms }) => {
              const pct = Math.min((ms / totalMs) * 100, 100);
              return (
                <div key={key} className="space-y-0.5">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{label}</span>
                    <span className="tabular-nums font-mono">{formatMs(ms)}</span>
                  </div>
                  <div className="h-1 w-full overflow-hidden rounded-full bg-muted">
                    <div
                      className="h-full rounded-full bg-primary/40 transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
