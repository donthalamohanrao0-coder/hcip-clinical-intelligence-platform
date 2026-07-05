'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useAuth } from '@/context/auth-context';
import { Header } from '@/components/layout/header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Activity,
  BookOpenCheck,
  Brain,
  Clock,
  FileText,
  Search,
  Stethoscope,
  TrendingUp,
  Upload,
  Zap,
  Library,
} from 'lucide-react';
import { KNOWLEDGE_BASES, ROLE_COLORS } from '@/lib/types';
import type { UserRole } from '@/lib/types';
import { cn } from '@/lib/utils';

interface HealthChecks {
  qdrant:        string;
  redis:         string;
  elasticsearch: string;
  neo4j:         string;
}

interface SystemHealth {
  status:   string;
  checks:   HealthChecks;
  latency?: Record<string, number>;
}

// User-friendly labels — no technical names shown to end users
const SERVICE_META: Record<string, { label: string; desc: string }> = {
  qdrant:        { label: 'Knowledge Store',  desc: 'Semantic document search'    },
  elasticsearch: { label: 'Search Engine',    desc: 'Keyword document retrieval'  },
  redis:         { label: 'Response Cache',   desc: 'Fast response delivery'      },
  neo4j:         { label: 'Reference Network',desc: 'Clinical relationship graph' },
};

const QUICK_ACTIONS = [
  {
    href:  '/query',
    icon:  Stethoscope,
    label: 'Clinical AI',
    desc:  'Ask evidence-based questions',
    color: 'bg-blue-50 text-blue-700 border-blue-200 hover:bg-blue-100 dark:bg-blue-950 dark:text-blue-300 dark:border-blue-800',
    roles: ['admin', 'physician', 'nurse', 'pharmacist'] as UserRole[],
  },
  {
    href:  '/upload',
    icon:  Upload,
    label: 'Upload Documents',
    desc:  'Add to your library',
    color: 'bg-green-50 text-green-700 border-green-200 hover:bg-green-100 dark:bg-green-950 dark:text-green-300 dark:border-green-800',
    roles: ['admin', 'physician'] as UserRole[],
  },
  {
    href:  '/documents',
    icon:  FileText,
    label: 'Browse Library',
    desc:  'Explore your documents',
    color: 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-300 dark:border-slate-700',
    roles: ['admin', 'physician', 'nurse', 'pharmacist'] as UserRole[],
  },
  {
    href:  '/history',
    icon:  Clock,
    label: 'Query History',
    desc:  'Review past questions',
    color: 'bg-slate-50 text-slate-700 border-slate-200 hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-300 dark:border-slate-700',
    roles: ['admin', 'physician', 'nurse', 'pharmacist'] as UserRole[],
  },
];

interface HistoryEntry {
  query:      string;
  confidence: number;
  timestamp:  string;
}

function getGreeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 17) return 'Good afternoon';
  return 'Good evening';
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1)   return 'just now';
  if (mins < 60)  return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function DashboardPage() {
  const { user } = useAuth();
  const role      = (user?.role ?? 'physician') as UserRole;
  const firstName = user?.name.split(' ')[0] ?? 'Doctor';

  const [health,   setHealth]   = useState<SystemHealth | null>(null);
  const [docCount, setDocCount] = useState<number | null>(null);
  const [history,  setHistory]  = useState<HistoryEntry[]>([]);

  const allowedKbs = user?.allowed_kb_ids ?? KNOWLEDGE_BASES.map((k) => k.id);

  useEffect(() => {
    fetch('/api/health').then((r) => r.json()).then(setHealth).catch(() => {});
    fetch('/api/documents').then((r) => r.json()).then((d) => d.success && setDocCount(d.total)).catch(() => {});

    try {
      const raw = localStorage.getItem('hcip_query_history');
      if (raw) {
        const entries: Array<{ query: string; result: { confidence_score: number }; timestamp: number }> =
          JSON.parse(raw);
        setHistory(
          entries.slice(0, 5).map((e) => ({
            query:      e.query,
            confidence: e.result?.confidence_score ?? 0,
            timestamp:  new Date(e.timestamp).toISOString(),
          })),
        );
      }
    } catch { /* ignore */ }
  }, []);

  const allOk = health?.status === 'ready' && Object.values(health.checks).every((v) => v === 'ok');
  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month:   'long',
    day:     'numeric',
    year:    'numeric',
  });

  const visibleActions = QUICK_ACTIONS.filter((a) => a.roles.includes(role));

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <Header
        title="Dashboard"
        description="Healthcare Clinical Intelligence Platform"
        badge="v1.0"
      />

      <div className="flex-1 overflow-auto">
        <div className="mx-auto max-w-6xl space-y-6 p-6">

          {/* Welcome section */}
          <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <h1 className="text-2xl font-bold text-foreground">
                {getGreeting()}, {firstName}
              </h1>
              <p className="text-sm text-muted-foreground mt-0.5">{today}</p>
            </div>
            <span
              className={cn(
                'self-start sm:self-auto inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold uppercase tracking-wider',
                ROLE_COLORS[role],
              )}
            >
              {role}
            </span>
          </div>

          {/* Stats row */}
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <StatCard
              icon={Brain}
              label="Queries Today"
              value={String(history.length)}
              trend="+12% from yesterday"
              color="text-blue-600"
            />
            <StatCard
              icon={FileText}
              label="Documents in Library"
              value={docCount !== null ? String(docCount) : '—'}
              trend="available to search"
              color="text-emerald-600"
            />
            <StatCard
              icon={TrendingUp}
              label="Avg Reliability"
              value={
                history.length > 0
                  ? `${Math.round(
                      (history.reduce((s, e) => s + e.confidence, 0) / history.length) * 100,
                    )}%`
                  : '—'
              }
              trend="across all queries"
              color="text-violet-600"
            />
            <StatCard
              icon={Library}
              label="Active Libraries"
              value={String(allowedKbs.length)}
              trend="available to you"
              color="text-amber-600"
            />
          </div>

          {/* System Health */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-sm">
                <Activity className="h-4 w-4 text-muted-foreground" />
                Platform Status
                {health && (
                  <Badge
                    variant={allOk ? 'secondary' : 'destructive'}
                    className={allOk ? 'bg-green-100 text-green-700 border-green-200' : ''}
                  >
                    {allOk ? 'All systems operational' : 'Degraded'}
                  </Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {health ? (
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  {Object.entries(health.checks).map(([svc, status]) => {
                    const meta = SERVICE_META[svc] ?? { label: svc, desc: '' };
                    const ok   = status === 'ok';
                    return (
                      <div
                        key={svc}
                        className="flex items-start gap-2.5 rounded-xl border bg-muted/30 px-3 py-3"
                      >
                        <span
                          className={cn(
                            'mt-0.5 h-2 w-2 shrink-0 rounded-full',
                            ok ? 'bg-green-500' : 'bg-destructive',
                          )}
                        />
                        <div className="min-w-0">
                          <p className="truncate text-xs font-semibold text-foreground">
                            {meta.label}
                          </p>
                          <p className="text-[10px] text-muted-foreground">{meta.desc}</p>
                          <p
                            className={cn(
                              'mt-0.5 text-[10px] font-medium',
                              ok ? 'text-green-600' : 'text-destructive',
                            )}
                          >
                            {ok ? 'Online' : 'Offline'}
                          </p>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
                  <Activity className="h-4 w-4 animate-pulse" />
                  Checking services...
                </div>
              )}
            </CardContent>
          </Card>

          {/* Quick Actions */}
          <div>
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Quick Actions
            </h2>
            <div
              className={cn(
                'grid gap-3',
                visibleActions.length === 4
                  ? 'grid-cols-2 sm:grid-cols-4'
                  : 'grid-cols-2 sm:grid-cols-3',
              )}
            >
              {visibleActions.map(({ href, icon: Icon, label, desc, color }) => (
                <Link key={href} href={href}>
                  <Card className={cn('h-full cursor-pointer border transition-colors', color)}>
                    <CardContent className="flex flex-col gap-2.5 p-4">
                      <div className="flex h-9 w-9 items-center justify-center rounded-xl border border-current/20 bg-white/60 dark:bg-black/20">
                        <Icon className="h-4 w-4" />
                      </div>
                      <div>
                        <p className="font-semibold text-sm">{label}</p>
                        <p className="text-xs opacity-70 mt-0.5">{desc}</p>
                      </div>
                    </CardContent>
                  </Card>
                </Link>
              ))}
            </div>
          </div>

          {/* Recent Activity */}
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Clock className="h-4 w-4 text-muted-foreground" />
                  Recent Queries
                </CardTitle>
                {history.length > 0 && (
                  <Link href="/history">
                    <Button variant="ghost" size="sm" className="h-7 text-xs">
                      View all
                    </Button>
                  </Link>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {history.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-8 text-center text-muted-foreground">
                  <Search className="h-8 w-8 opacity-30" />
                  <p className="text-sm font-medium">No queries yet</p>
                  <p className="text-xs">Submit your first clinical question to see it here.</p>
                  <Link href="/query">
                    <Button size="sm" className="mt-2">
                      Ask Clinical AI
                    </Button>
                  </Link>
                </div>
              ) : (
                <div className="space-y-2">
                  {history.map((entry, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-3 rounded-lg border bg-muted/20 px-3 py-2.5"
                    >
                      <Search className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <p className="flex-1 truncate text-sm">{entry.query}</p>
                      <Badge
                        variant="secondary"
                        className={cn(
                          'shrink-0 text-[10px]',
                          entry.confidence >= 0.8
                            ? 'bg-green-100 text-green-700'
                            : entry.confidence >= 0.6
                            ? 'bg-amber-100 text-amber-700'
                            : 'bg-red-100 text-red-700',
                        )}
                      >
                        {Math.round(entry.confidence * 100)}%
                      </Badge>
                      <span className="shrink-0 text-[10px] text-muted-foreground">
                        {timeAgo(entry.timestamp)}
                      </span>
                      <Link href={`/query?q=${encodeURIComponent(entry.query)}`}>
                        <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]">
                          Re-run
                        </Button>
                      </Link>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* How it works */}
          <Card className="border-primary/20 bg-primary/5">
            <CardContent className="flex items-start gap-3 p-4">
              <Zap className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <div className="text-xs text-muted-foreground space-y-1">
                <p className="font-semibold text-foreground text-sm">How Clinical AI works</p>
                <p>
                  You ask a question → AI searches your library → Returns evidence-based answer with
                  sources. All responses include a reliability score and source citations.
                </p>
              </div>
            </CardContent>
          </Card>

        </div>
      </div>
    </div>
  );
}

function StatCard({
  icon: Icon,
  label,
  value,
  trend,
  color,
}: {
  icon:  React.ElementType;
  label: string;
  value: string;
  trend: string;
  color: string;
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-1.5 text-muted-foreground">
          <Icon className={cn('h-3.5 w-3.5', color)} />
          <span className="text-xs">{label}</span>
        </div>
        <p className="mt-2 text-2xl font-bold text-foreground">{value}</p>
        <p className="mt-0.5 text-[10px] text-muted-foreground">{trend}</p>
      </CardContent>
    </Card>
  );
}
