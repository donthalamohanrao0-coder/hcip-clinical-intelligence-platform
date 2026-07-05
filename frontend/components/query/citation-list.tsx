import { ExternalLink, FileText, Database } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import type { Citation } from "@/lib/types";

interface CitationListProps {
  citations: Citation[];
}

function CitationIcon({ source }: { source: Citation["source"] }) {
  if (source === "pubmed") return <ExternalLink className="h-3.5 w-3.5 text-blue-500" />;
  if (source === "neo4j")  return <Database className="h-3.5 w-3.5 text-purple-500" />;
  return <FileText className="h-3.5 w-3.5 text-primary" />;
}

function SourceBadge({ source }: { source: Citation["source"] }) {
  const labels: Record<string, string> = {
    pubmed:        "PubMed",
    qdrant:        "Vector DB",
    elasticsearch: "BM25",
    neo4j:         "Knowledge Graph",
  };
  return (
    <Badge variant="outline" className="text-[10px]">
      {labels[source] ?? source}
    </Badge>
  );
}

export function CitationList({ citations }: CitationListProps) {
  if (citations.length === 0) return null;

  return (
    <div className="space-y-3">
      <h3 className="flex items-center gap-2 text-sm font-semibold text-muted-foreground">
        <FileText className="h-4 w-4" />
        Citations ({citations.length})
      </h3>

      <div className="space-y-2">
        {citations.map((cite, idx) => (
          <div key={cite.chunk_id + idx} className="rounded-lg border bg-muted/30 p-3">
            <div className="flex items-start gap-2.5">
              {/* Ref number */}
              <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[11px] font-bold text-primary">
                {cite.ref_number}
              </span>

              <div className="flex-1 space-y-1">
                {/* Header row */}
                <div className="flex flex-wrap items-center gap-1.5">
                  <CitationIcon source={cite.source} />
                  <SourceBadge source={cite.source} />
                  {cite.specialty && (
                    <Badge variant="secondary" className="text-[10px] capitalize">
                      {cite.specialty}
                    </Badge>
                  )}
                  {cite.approval_status && cite.approval_status !== "approved" && (
                    <Badge variant="warning" className="text-[10px]">
                      {cite.approval_status}
                    </Badge>
                  )}
                </div>

                {/* PubMed citation */}
                {cite.source === "pubmed" && (
                  <div className="space-y-0.5 text-xs">
                    {cite.title && (
                      <p className="font-medium leading-snug">{cite.title}</p>
                    )}
                    {cite.authors && cite.authors.length > 0 && (
                      <p className="text-muted-foreground">
                        {cite.authors.slice(0, 3).join(", ")}
                        {cite.authors.length > 3 ? " et al." : ""}
                      </p>
                    )}
                    <p className="text-muted-foreground">
                      {[cite.journal, cite.year].filter(Boolean).join(" · ")}
                      {cite.pmid && ` · PMID: ${cite.pmid}`}
                    </p>
                    {cite.url && (
                      <a
                        href={cite.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="inline-flex items-center gap-1 text-primary hover:underline"
                      >
                        View on PubMed
                        <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                )}

                {/* Internal citation */}
                {cite.source !== "pubmed" && (
                  <div className="space-y-0.5 text-xs">
                    {cite.document_type && (
                      <p className="font-medium capitalize">
                        {cite.document_type.replace(/_/g, " ")}
                      </p>
                    )}
                    {cite.section && (
                      <p className="text-muted-foreground">Section: {cite.section}</p>
                    )}
                    {typeof cite.citation_score === "number" && (
                      <p className="text-muted-foreground">
                        Relevance: {Math.round(cite.citation_score * 100)}%
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
