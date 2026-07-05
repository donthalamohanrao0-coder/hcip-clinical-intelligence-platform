'use client';

import { useState } from 'react';
import { Loader2, Send, Stethoscope } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { KNOWLEDGE_BASES } from '@/lib/types';
import type { KnowledgeBase } from '@/lib/types';

interface QueryInputProps {
  onSubmit:    (query: string, kbId: string) => void;
  isLoading:   boolean;
  allowedKbs?: KnowledgeBase[];   // if omitted, show all KBs
}

const EXAMPLE_QUERIES = [
  'First-line treatment for type 2 diabetes in CKD stage 3?',
  'Drug interactions between warfarin and NSAIDs in elderly patients?',
  'Management of hypertensive emergency in pregnancy?',
  'Empirical antibiotic therapy for community-acquired pneumonia?',
];

export function QueryInput({ onSubmit, isLoading, allowedKbs }: QueryInputProps) {
  const kbs        = allowedKbs ?? KNOWLEDGE_BASES;
  const defaultKb  = process.env.NEXT_PUBLIC_DEFAULT_KB_ID ?? kbs[0]?.id ?? KNOWLEDGE_BASES[0].id;

  const [query, setQuery] = useState('');
  const [kbId,  setKbId]  = useState(defaultKb);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = query.trim();
    if (!trimmed || isLoading) return;
    onSubmit(trimmed, kbId);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      handleSubmit(e as unknown as React.FormEvent);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* Query textarea */}
      <div className="space-y-2">
        <Label htmlFor="query-input" className="flex items-center gap-2">
          <Stethoscope className="h-4 w-4 text-primary" />
          Clinical Question
        </Label>
        <Textarea
          id="query-input"
          placeholder="e.g. First-line treatment for type 2 diabetes in CKD stage 3?"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={4}
          className="resize-none text-base leading-relaxed"
          disabled={isLoading}
          maxLength={2000}
          aria-describedby="query-hint"
        />
        <p id="query-hint" className="text-xs text-muted-foreground">
          Press{' '}
          <kbd className="rounded border bg-muted px-1 py-0.5 text-[10px] font-mono">
            ⌘ Enter
          </kbd>{' '}
          to submit · {query.length}/2000
        </p>
      </div>

      {/* Knowledge base selector + submit */}
      <div className="flex items-end gap-3">
        <div className="flex-1 space-y-2">
          <Label htmlFor="kb-select">Knowledge Base</Label>
          <Select value={kbId} onValueChange={setKbId} disabled={isLoading}>
            <SelectTrigger id="kb-select">
              <SelectValue placeholder="Select knowledge base..." />
            </SelectTrigger>
            <SelectContent>
              {kbs.map((kb) => (
                <SelectItem key={kb.id} value={kb.id}>
                  {kb.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <Button
          type="submit"
          size="lg"
          disabled={!query.trim() || isLoading}
          className="min-w-[140px]"
        >
          {isLoading ? (
            <>
              <Loader2 className="animate-spin" />
              Processing…
            </>
          ) : (
            <>
              <Send />
              Submit Query
            </>
          )}
        </Button>
      </div>

      {/* Example queries */}
      {!query && (
        <div className="space-y-1">
          <p className="text-xs font-medium text-muted-foreground">Example queries:</p>
          <div className="flex flex-wrap gap-2">
            {EXAMPLE_QUERIES.map((q) => (
              <button
                key={q}
                type="button"
                onClick={() => setQuery(q)}
                className="rounded-full border border-dashed px-3 py-1 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-primary"
              >
                {q.length > 55 ? q.slice(0, 52) + '…' : q}
              </button>
            ))}
          </div>
        </div>
      )}
    </form>
  );
}
