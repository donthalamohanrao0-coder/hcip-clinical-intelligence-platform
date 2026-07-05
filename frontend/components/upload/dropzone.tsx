"use client";

import { useCallback, useRef, useState } from "react";
import { Upload, FileText, X, CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { KNOWLEDGE_BASES } from "@/lib/types";

interface UploadedFile {
  id: string;
  file: File;
  status: "pending" | "uploading" | "success" | "error";
  progress: number;
  message?: string;
  documentId?: string;
  chunksCreated?: number;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

const ACCEPTED = ".pdf,.txt,.csv,.json,.md";
const ACCEPTED_LABEL = "PDF, TXT, CSV, JSON, MD";
const MAX_MB = 50;

export function Dropzone() {
  const [isDragging, setIsDragging] = useState(false);
  const [files, setFiles] = useState<UploadedFile[]>([]);
  const [kbId, setKbId] = useState("kb-clinical-2024");
  const inputRef = useRef<HTMLInputElement>(null);

  const addFiles = (newFiles: FileList | File[]) => {
    const arr = Array.from(newFiles);
    const entries: UploadedFile[] = arr.map((f) => ({
      id: `${f.name}-${Date.now()}-${Math.random()}`,
      file: f,
      status: "pending",
      progress: 0,
    }));
    setFiles((prev) => [...prev, ...entries]);
    entries.forEach((entry) => uploadFile(entry, kbId));
  };

  const uploadFile = async (entry: UploadedFile, knowledgeBaseId: string) => {
    setFiles((prev) =>
      prev.map((f) => (f.id === entry.id ? { ...f, status: "uploading", progress: 10 } : f)),
    );

    try {
      const formData = new FormData();
      formData.append("file", entry.file);
      formData.append("knowledge_base_id", knowledgeBaseId);

      // Simulate progress ticks while waiting
      const ticker = setInterval(() => {
        setFiles((prev) =>
          prev.map((f) =>
            f.id === entry.id && f.progress < 85
              ? { ...f, progress: f.progress + 5 }
              : f,
          ),
        );
      }, 400);

      const res = await fetch("/api/upload", { method: "POST", body: formData });
      clearInterval(ticker);

      const data = await res.json();
      if (res.ok && data.success) {
        setFiles((prev) =>
          prev.map((f) =>
            f.id === entry.id
              ? {
                  ...f,
                  status: "success",
                  progress: 100,
                  message: data.message,
                  documentId: data.document_id,
                  chunksCreated: data.chunks_created,
                }
              : f,
          ),
        );
      } else {
        throw new Error(data.detail ?? data.error ?? "Upload failed");
      }
    } catch (err) {
      setFiles((prev) =>
        prev.map((f) =>
          f.id === entry.id
            ? { ...f, status: "error", progress: 0, message: String(err) }
            : f,
        ),
      );
    }
  };

  const removeFile = (id: string) => setFiles((prev) => prev.filter((f) => f.id !== id));
  const retryFile = (entry: UploadedFile) => uploadFile(entry, kbId);

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
    },
    [kbId],
  );

  return (
    <div className="space-y-4">
      {/* Library selector */}
      <div className="flex items-center gap-3">
        <span className="text-sm font-medium text-muted-foreground">Target library</span>
        <Select value={kbId} onValueChange={setKbId}>
          <SelectTrigger className="w-56">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {KNOWLEDGE_BASES.map((kb) => (
              <SelectItem key={kb.id} value={kb.id}>
                {kb.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Drop zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        className={cn(
          "flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-8 py-14 transition-colors",
          isDragging
            ? "border-primary bg-primary/5"
            : "border-muted-foreground/25 hover:border-primary/50 hover:bg-accent/30",
        )}
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPTED}
          multiple
          className="hidden"
          onChange={(e) => e.target.files && addFiles(e.target.files)}
        />
        <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-primary/10">
          <Upload className="h-6 w-6 text-primary" />
        </div>
        <p className="text-center font-medium">
          Drag &amp; drop files here, or <span className="text-primary underline">browse</span>
        </p>
        <p className="mt-1 text-center text-sm text-muted-foreground">
          {ACCEPTED_LABEL} &bull; Max {MAX_MB} MB per file
        </p>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="space-y-2">
          {files.map((entry) => (
            <FileRow
              key={entry.id}
              entry={entry}
              onRemove={() => removeFile(entry.id)}
              onRetry={() => retryFile(entry)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function FileRow({
  entry,
  onRemove,
  onRetry,
}: {
  entry: UploadedFile;
  onRemove: () => void;
  onRetry: () => void;
}) {
  const { file, status, progress, message, chunksCreated } = entry;

  return (
    <div className="flex items-start gap-3 rounded-lg border bg-card p-3">
      <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted">
        <FileText className="h-4 w-4 text-muted-foreground" />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-center justify-between gap-2">
          <p className="truncate text-sm font-medium">{file.name}</p>
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">{formatBytes(file.size)}</span>
            {status === "success" && (
              <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
            )}
            {status === "error" && (
              <AlertCircle className="h-4 w-4 shrink-0 text-destructive" />
            )}
            {status === "uploading" && (
              <Loader2 className="h-4 w-4 shrink-0 animate-spin text-primary" />
            )}
            <button onClick={onRemove} className="ml-1 text-muted-foreground hover:text-foreground">
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {status === "uploading" && (
          <Progress value={progress} className="mt-2 h-1.5" />
        )}

        {status === "success" && (
          <div className="mt-1 flex items-center gap-2">
            <Badge variant="secondary" className="text-[10px]">
              {chunksCreated} sections added
            </Badge>
            <span className="text-xs text-green-600 dark:text-green-400">{message}</span>
          </div>
        )}

        {status === "error" && (
          <div className="mt-1 flex items-center gap-2">
            <span className="text-xs text-destructive">{message}</span>
            <button
              onClick={onRetry}
              className="text-xs text-primary underline hover:no-underline"
            >
              Retry
            </button>
          </div>
        )}

        {status === "pending" && (
          <p className="mt-1 text-xs text-muted-foreground">Queued…</p>
        )}
      </div>
    </div>
  );
}
