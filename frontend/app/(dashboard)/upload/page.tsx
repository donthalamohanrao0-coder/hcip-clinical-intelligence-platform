"use client";

import { Header } from "@/components/layout/header";
import { Dropzone } from "@/components/upload/dropzone";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { FileText, Shield, BookMarked } from "lucide-react";

const SUPPORTED_FORMATS = [
  { ext: "PDF", desc: "Clinical guidelines, research papers, drug labels" },
  { ext: "TXT", desc: "Plain text protocols and notes" },
  { ext: "CSV", desc: "Structured data, drug databases" },
  { ext: "JSON", desc: "FHIR resources, structured medical records" },
  { ext: "MD",  desc: "Markdown documentation and SOPs" },
];

const PIPELINE_STEPS = [
  { icon: FileText,    label: "Read document",          desc: "Content is extracted from your file" },
  { icon: BookMarked,  label: "Process & understand",   desc: "Document sections are identified and analyzed" },
  { icon: Shield,      label: "Add to your library",    desc: "Instantly available for clinical questions" },
];

export default function UploadPage() {
  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <Header
        title="Upload Documents"
        description="Add clinical guidelines, SOPs, research papers and drug data to your library"
        badge="Direct Upload"
      />

      <div className="overflow-auto">
        <div className="mx-auto max-w-4xl space-y-6 p-6">
          {/* Main upload card */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-base">Upload Files</CardTitle>
              <CardDescription>
                Files are processed and added to your chosen library immediately after upload.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <Dropzone />
            </CardContent>
          </Card>

          <div className="grid gap-4 sm:grid-cols-2">
            {/* Supported formats */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Supported Formats</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {SUPPORTED_FORMATS.map(({ ext, desc }) => (
                  <div key={ext} className="flex items-start gap-2">
                    <Badge variant="outline" className="mt-0.5 shrink-0 font-mono text-[10px]">
                      {ext}
                    </Badge>
                    <span className="text-xs text-muted-foreground">{desc}</span>
                  </div>
                ))}
              </CardContent>
            </Card>

            {/* What happens steps */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">What happens to your file</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                {PIPELINE_STEPS.map(({ icon: Icon, label, desc }, i) => (
                  <div key={label} className="flex items-start gap-3">
                    <div className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
                      {i + 1}
                    </div>
                    <div>
                      <p className="text-sm font-medium">{label}</p>
                      <p className="text-xs text-muted-foreground">{desc}</p>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>

          {/* Note */}
          <p className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-800 dark:border-amber-900/50 dark:bg-amber-950/20 dark:text-amber-300">
            <strong>Note:</strong> Uploaded documents are available for clinical queries immediately.
            All uploads are scoped to the selected library. For production governance workflows
            (review, approval, versioning), use the full ingestion pipeline.
          </p>
        </div>
      </div>
    </div>
  );
}
