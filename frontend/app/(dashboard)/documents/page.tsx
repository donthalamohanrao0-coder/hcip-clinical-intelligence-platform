"use client";

import { useEffect, useState } from "react";
import { Header } from "@/components/layout/header";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  FileText,
  FileSpreadsheet,
  FileCode,
  FileJson,
  File,
  Trash2,
  RefreshCw,
  Upload,
  AlertCircle,
  Library,
  AlertTriangle,
  X,
} from "lucide-react";
import Link from "next/link";

interface DocumentInfo {
  document_id:       string;
  file_name:         string;
  file_type:         string;
  knowledge_base_id: string;
  chunks_created:    number;
  uploaded_at:       string;
  status:            string;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1)  return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

const KB_LABELS: Record<string, string> = {
  "kb-clinical-2024": "Clinical Guidelines",
  "kb-pharmacology":  "Pharmacology",
  "kb-cardiology":    "Cardiology",
  "kb-oncology":      "Oncology",
  "kb-emergency":     "Emergency Medicine",
};

function FileIcon({ fileType }: { fileType: string }) {
  const ext = fileType.toLowerCase().replace(".", "");
  if (ext === "pdf")             return <FileText className="h-5 w-5 text-red-500" />;
  if (ext === "csv")             return <FileSpreadsheet className="h-5 w-5 text-green-600" />;
  if (ext === "json")            return <FileJson className="h-5 w-5 text-amber-500" />;
  if (ext === "md")              return <FileCode className="h-5 w-5 text-blue-500" />;
  if (ext === "txt")             return <FileText className="h-5 w-5 text-slate-500" />;
  return <File className="h-5 w-5 text-muted-foreground" />;
}

// ── Confirmation dialog ──────────────────────────────────────────────────────

function DeleteConfirmDialog({
  fileName,
  onConfirm,
  onCancel,
}: {
  fileName:  string;
  onConfirm: () => void;
  onCancel:  () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onCancel}
      />
      {/* Dialog */}
      <div className="relative z-10 mx-4 w-full max-w-sm rounded-2xl border bg-background p-6 shadow-xl">
        <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-destructive/10">
          <AlertTriangle className="h-6 w-6 text-destructive" />
        </div>
        <h3 className="text-base font-semibold text-foreground">Remove document?</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          <span className="font-medium text-foreground">{fileName}</span> will be removed from your
          library and will no longer be searchable. This action cannot be undone.
        </p>
        <div className="mt-5 flex gap-2">
          <Button variant="outline" size="sm" className="flex-1" onClick={onCancel}>
            Cancel
          </Button>
          <Button variant="destructive" size="sm" className="flex-1" onClick={onConfirm}>
            Remove
          </Button>
        </div>
        <button
          onClick={onCancel}
          className="absolute right-4 top-4 text-muted-foreground hover:text-foreground"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

// ── Main page ────────────────────────────────────────────────────────────────

export default function DocumentsPage() {
  const [docs,     setDocs]     = useState<DocumentInfo[]>([]);
  const [loading,  setLoading]  = useState(true);
  const [error,    setError]    = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<DocumentInfo | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const res  = await fetch("/api/documents", { cache: "no-store" });
      const data = await res.json();
      if (data.success) {
        setDocs(data.documents);
      } else {
        setError(data.error ?? "Failed to load documents");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function doDelete(id: string) {
    setConfirmDelete(null);
    setDeleting(id);
    try {
      await fetch(`/api/documents/${id}`, { method: "DELETE" });
      setDocs((prev) => prev.filter((d) => d.document_id !== id));
    } finally {
      setDeleting(null);
    }
  }

  useEffect(() => { load(); }, []);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <Header
        title="Document Library"
        description="Documents in your library, available for clinical AI queries"
      />

      {/* Confirm dialog */}
      {confirmDelete && (
        <DeleteConfirmDialog
          fileName={confirmDelete.file_name}
          onConfirm={() => doDelete(confirmDelete.document_id)}
          onCancel={() => setConfirmDelete(null)}
        />
      )}

      <div className="overflow-auto">
        <div className="mx-auto max-w-5xl p-6">
          {/* Toolbar */}
          <div className="mb-4 flex items-center justify-between">
            <p className="text-sm text-muted-foreground">
              {loading
                ? "Loading…"
                : `${docs.length} document${docs.length !== 1 ? "s" : ""} in library`}
            </p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={load} disabled={loading}>
                <RefreshCw className={`mr-1.5 h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
                Refresh
              </Button>
              <Button size="sm" asChild>
                <Link href="/upload">
                  <Upload className="mr-1.5 h-3.5 w-3.5" />
                  Upload
                </Link>
              </Button>
            </div>
          </div>

          {/* Error state */}
          {error && (
            <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {error}
            </div>
          )}

          {/* Loading state */}
          {loading && !error && (
            <div className="space-y-2">
              {[1, 2, 3].map((i) => (
                <Skeleton key={i} className="h-20 w-full rounded-lg" />
              ))}
            </div>
          )}

          {/* Empty state */}
          {!loading && !error && docs.length === 0 && (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed py-20 text-center text-muted-foreground">
              <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-muted">
                <Library className="h-6 w-6 opacity-40" />
              </div>
              <p className="font-medium text-foreground">Your library is empty</p>
              <p className="mt-1 text-sm max-w-xs">
                Upload clinical documents to start searching with Clinical AI.
              </p>
              <Button size="sm" className="mt-4" asChild>
                <Link href="/upload">
                  <Upload className="mr-1.5 h-3.5 w-3.5" />
                  Upload your first document
                </Link>
              </Button>
            </div>
          )}

          {/* Document list */}
          {!loading && docs.length > 0 && (
            <div className="space-y-2">
              {docs.map((doc) => (
                <Card key={doc.document_id} className="overflow-hidden">
                  <CardContent className="flex items-center gap-4 p-4">
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
                      <FileIcon fileType={doc.file_type} />
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="truncate font-medium text-sm">{doc.file_name}</p>
                        <Badge variant="outline" className="font-mono text-[10px] shrink-0">
                          {doc.file_type.toUpperCase().replace(".", "")}
                        </Badge>
                        <Badge
                          variant="secondary"
                          className="text-[10px] shrink-0 bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                        >
                          {doc.status}
                        </Badge>
                      </div>
                      <div className="mt-0.5 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                        <span>{KB_LABELS[doc.knowledge_base_id] ?? doc.knowledge_base_id}</span>
                        <span>&bull;</span>
                        <span>{doc.chunks_created} sections</span>
                        <span>&bull;</span>
                        <span>{timeAgo(doc.uploaded_at)}</span>
                      </div>
                    </div>

                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 shrink-0 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
                      onClick={() => setConfirmDelete(doc)}
                      disabled={deleting === doc.document_id}
                    >
                      <Trash2
                        className={`h-4 w-4 ${
                          deleting === doc.document_id ? "animate-pulse" : ""
                        }`}
                      />
                    </Button>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
