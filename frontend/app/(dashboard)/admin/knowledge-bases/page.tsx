'use client';

import { useState, useEffect } from 'react';
import { Header } from '@/components/layout/header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Activity,
  BookOpen,
  Brain,
  FileText,
  FlaskConical,
  Heart,
  Pill,
  Shield,
  ToggleLeft,
  ToggleRight,
  Users,
} from 'lucide-react';
import { KNOWLEDGE_BASES, ROLE_COLORS, ROLE_LABELS } from '@/lib/types';
import type { UserRole } from '@/lib/types';
import { cn } from '@/lib/utils';

interface KBMeta {
  icon:          React.ElementType;
  color:         string;
  borderColor:   string;
  iconBg:        string;
  assignedRoles: UserRole[];
}

// Card metadata (icons, colors) never changes and never gets persisted —
// only `isActive` is user-editable state, kept separately below. Storing the
// icon component itself in localStorage silently breaks: JSON.stringify()
// drops function-valued properties, so after one save `cfg.icon` comes back
// `undefined` and rendering `<Icon />` crashes the page.
const KB_META: Record<string, KBMeta> = {
  'kb-clinical-2024': {
    icon:          BookOpen,
    color:         'text-blue-700',
    borderColor:   'border-blue-200',
    iconBg:        'bg-blue-50',
    assignedRoles: ['admin', 'physician', 'nurse', 'pharmacist'],
  },
  'kb-pharmacology': {
    icon:          Pill,
    color:         'text-amber-700',
    borderColor:   'border-amber-200',
    iconBg:        'bg-amber-50',
    assignedRoles: ['admin', 'physician', 'pharmacist'],
  },
  'kb-cardiology': {
    icon:          Heart,
    color:         'text-red-700',
    borderColor:   'border-red-200',
    iconBg:        'bg-red-50',
    assignedRoles: ['admin', 'physician'],
  },
  'kb-oncology': {
    icon:          FlaskConical,
    color:         'text-violet-700',
    borderColor:   'border-violet-200',
    iconBg:        'bg-violet-50',
    assignedRoles: ['admin', 'physician'],
  },
  'kb-emergency': {
    icon:          Shield,
    color:         'text-emerald-700',
    borderColor:   'border-emerald-200',
    iconBg:        'bg-emerald-50',
    assignedRoles: ['admin', 'physician', 'nurse'],
  },
};

const STORAGE_KEY = 'hcip_kb_active_v2';

export default function KnowledgeBasesPage() {
  // Only the active/inactive flag is persisted — plain booleans serialize fine.
  const [activeMap,  setActiveMap]  = useState<Record<string, boolean>>({});
  const [docCounts,  setDocCounts]  = useState<Record<string, number>>({});
  const [isLoadingCounts, setIsLoadingCounts] = useState(true);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      setActiveMap(raw ? JSON.parse(raw) : {});
    } catch {
      setActiveMap({});
    }
  }, []);

  // Real document counts per library, derived from the same endpoint the
  // Documents page uses — no more hardcoded seed numbers.
  useEffect(() => {
    (async () => {
      try {
        const res  = await fetch('/api/documents', { cache: 'no-store' });
        const data = await res.json();
        const counts: Record<string, number> = {};
        for (const doc of data.documents ?? []) {
          counts[doc.knowledge_base_id] = (counts[doc.knowledge_base_id] ?? 0) + 1;
        }
        setDocCounts(counts);
      } catch {
        setDocCounts({});
      } finally {
        setIsLoadingCounts(false);
      }
    })();
  }, []);

  const configs = KNOWLEDGE_BASES.map(kb => ({
    id:        kb.id,
    isActive:  activeMap[kb.id] ?? true,
    docCount:  docCounts[kb.id] ?? 0,
    ...KB_META[kb.id],
  }));

  const toggleKB = (id: string) => {
    const updated = { ...activeMap, [id]: !(activeMap[id] ?? true) };
    setActiveMap(updated);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(updated));
  };

  const totalDocs   = configs.reduce((s, c) => s + c.docCount, 0);
  const activeKBs   = configs.filter(c => c.isActive).length;

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <Header
        title="Library Management"
        description="Configure access controls and monitor document libraries"
        badge="Admin"
      />

      <div className="flex-1 overflow-auto">
        <div className="mx-auto max-w-6xl space-y-6 p-6">

          {/* Stats */}
          <div className="grid grid-cols-3 gap-4">
            {[
              { label: 'Total Libraries',       value: configs.length,    icon: Brain,    color: 'text-blue-600'   },
              { label: 'Active',                value: activeKBs,         icon: Activity, color: 'text-green-600'  },
              { label: 'Total Documents',       value: totalDocs,         icon: FileText, color: 'text-violet-600' },
            ].map(s => (
              <Card key={s.label}>
                <CardContent className="p-4">
                  <div className="flex items-center gap-1.5 text-muted-foreground">
                    <s.icon className={cn('h-3.5 w-3.5', s.color)} />
                    <span className="text-xs">{s.label}</span>
                  </div>
                  <p className="mt-2 text-2xl font-bold">{s.value.toLocaleString()}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* KB Grid */}
          <div className="grid gap-5 sm:grid-cols-2 xl:grid-cols-3">
            {configs.map(cfg => {
              const kb   = KNOWLEDGE_BASES.find(k => k.id === cfg.id)!;
              const Icon = cfg.icon;
              return (
                <Card
                  key={cfg.id}
                  className={cn(
                    'relative overflow-hidden border-l-4 transition-all duration-200',
                    cfg.borderColor,
                    !cfg.isActive && 'opacity-60',
                  )}
                >
                  {/* Status dot */}
                  <div className="absolute right-4 top-4">
                    <span className={cn(
                      'flex h-2 w-2 rounded-full',
                      cfg.isActive ? 'bg-green-500' : 'bg-gray-300',
                    )} />
                  </div>

                  <CardContent className="p-5 space-y-4">
                    {/* Icon + Title */}
                    <div className="flex items-start gap-3">
                      <div className={cn('flex h-10 w-10 shrink-0 items-center justify-center rounded-xl', cfg.iconBg)}>
                        <Icon className={cn('h-5 w-5', cfg.color)} />
                      </div>
                      <div className="min-w-0 pr-4">
                        <h3 className="font-semibold text-sm text-foreground leading-snug">{kb.label}</h3>
                        <p className="text-xs text-muted-foreground mt-0.5">{kb.description}</p>
                      </div>
                    </div>

                    {/* Stats */}
                    <div className="flex items-center gap-4">
                      <div>
                        <p className="text-lg font-bold">{cfg.docCount.toLocaleString()}</p>
                        <p className="text-[10px] text-muted-foreground">documents</p>
                      </div>
                      <div className="h-8 w-px bg-border" />
                      <div>
                        <p className="text-lg font-bold">{cfg.assignedRoles.length}</p>
                        <p className="text-[10px] text-muted-foreground">roles assigned</p>
                      </div>
                    </div>

                    {/* Role badges */}
                    <div className="flex flex-wrap gap-1.5">
                      {cfg.assignedRoles.map(role => (
                        <span
                          key={role}
                          className={cn(
                            'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-medium',
                            ROLE_COLORS[role],
                          )}
                        >
                          {ROLE_LABELS[role]}
                        </span>
                      ))}
                    </div>

                    {/* Actions */}
                    <div className="flex items-center justify-between border-t pt-3">
                      <Button variant="outline" size="sm" className="h-7 text-xs">
                        <Users className="h-3 w-3" />
                        Manage Access
                      </Button>

                      <button
                        onClick={() => toggleKB(cfg.id)}
                        className={cn(
                          'flex items-center gap-1.5 text-xs font-medium transition-colors',
                          cfg.isActive ? 'text-green-600 hover:text-green-700' : 'text-muted-foreground hover:text-foreground',
                        )}
                        title={cfg.isActive ? 'Deactivate' : 'Activate'}
                      >
                        {cfg.isActive ? (
                          <ToggleRight className="h-5 w-5" />
                        ) : (
                          <ToggleLeft className="h-5 w-5" />
                        )}
                        {cfg.isActive ? 'Active' : 'Inactive'}
                      </button>
                    </div>
                  </CardContent>
                </Card>
              );
            })}
          </div>

          {/* Info card */}
          <Card className="border-primary/20 bg-primary/5">
            <CardContent className="flex items-start gap-3 p-4">
              <Brain className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <div className="text-xs text-muted-foreground space-y-1">
                <p className="font-semibold text-foreground text-sm">About Libraries</p>
                <p>
                  Each library is a collection of indexed clinical documents searchable by Clinical AI.
                  Access is controlled per role. Inactive libraries are excluded from query routing.
                </p>
              </div>
            </CardContent>
          </Card>

        </div>
      </div>
    </div>
  );
}
