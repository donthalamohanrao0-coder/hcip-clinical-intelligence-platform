"use client";

import { useEffect, useState } from "react";
import { Header } from "@/components/layout/header";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { useAuth } from "@/context/auth-context";
import { KNOWLEDGE_BASES, ROLE_LABELS, ROLE_COLORS } from "@/lib/types";
import type { UserRole } from "@/lib/types";
import {
  User,
  Shield,
  Library,
  Activity,
  CheckCircle2,
  XCircle,
  Info,
} from "lucide-react";
import { cn } from "@/lib/utils";

interface HealthChecks {
  qdrant:        string;
  redis:         string;
  elasticsearch: string;
  neo4j:         string;
}

interface SystemHealth {
  status:   string;
  checks:   HealthChecks;
}

// Admin-only: friendly names for services (no raw tech names)
const SERVICE_DISPLAY: Record<string, { label: string; desc: string }> = {
  qdrant:        { label: "Knowledge Store",   desc: "Semantic document search index"  },
  elasticsearch: { label: "Search Engine",     desc: "Full-text document retrieval"    },
  redis:         { label: "Response Cache",    desc: "Fast response caching layer"     },
  neo4j:         { label: "Reference Network", desc: "Clinical relationship graph"     },
};

export default function SettingsPage() {
  const { user, isAdmin } = useAuth();
  const role = (user?.role ?? "physician") as UserRole;

  const [health, setHealth] = useState<SystemHealth | null>(null);

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => {});
  }, []);

  const allowedKbs = KNOWLEDGE_BASES.filter((kb) =>
    (user?.allowed_kb_ids ?? []).includes(kb.id),
  );

  const allOk =
    health?.status === "ready" &&
    Object.values(health.checks).every((v) => v === "ok");

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      <Header title="Settings" description="Your account and platform information" />

      <div className="overflow-auto">
        <div className="mx-auto max-w-2xl space-y-6 p-6">

          {/* Account information */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <User className="h-4 w-4 text-muted-foreground" />
                Account
              </CardTitle>
              <CardDescription>Your profile and access level</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {user ? (
                <>
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium text-sm text-foreground">{user.name}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">{user.email}</p>
                    </div>
                    <span
                      className={cn(
                        "inline-flex items-center rounded-full border px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider",
                        ROLE_COLORS[role],
                      )}
                    >
                      {ROLE_LABELS[role]}
                    </span>
                  </div>

                  <Separator />

                  <div className="space-y-1">
                    <p className="text-xs font-medium text-muted-foreground">Account ID</p>
                    <p className="font-mono text-xs text-foreground/70 break-all">{user.id}</p>
                  </div>

                  {user.last_login && (
                    <div className="space-y-1">
                      <p className="text-xs font-medium text-muted-foreground">Last login</p>
                      <p className="text-xs text-foreground/70">
                        {new Date(user.last_login).toLocaleString()}
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">Not signed in</p>
              )}
            </CardContent>
          </Card>

          {/* Library access */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Library className="h-4 w-4 text-muted-foreground" />
                Library Access
              </CardTitle>
              <CardDescription>
                The clinical libraries available to your account
              </CardDescription>
            </CardHeader>
            <CardContent>
              {allowedKbs.length > 0 ? (
                <div className="space-y-2">
                  {allowedKbs.map((kb) => (
                    <div
                      key={kb.id}
                      className="flex items-start gap-3 rounded-lg border bg-muted/20 px-3 py-2.5"
                    >
                      <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-500" />
                      <div>
                        <p className="text-sm font-medium text-foreground">{kb.label}</p>
                        {kb.description && (
                          <p className="text-xs text-muted-foreground">{kb.description}</p>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">No libraries assigned.</p>
              )}
            </CardContent>
          </Card>

          {/* Platform version */}
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Info className="h-4 w-4 text-muted-foreground" />
                Platform
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-2 text-sm">
              <div className="flex justify-between text-muted-foreground">
                <span>Application version</span>
                <span className="font-mono text-foreground">v1.0.0</span>
              </div>
              <div className="flex justify-between text-muted-foreground">
                <span>Clinical AI version</span>
                <span className="font-mono text-foreground">v1.0.0</span>
              </div>
            </CardContent>
          </Card>

          {/* Admin-only: service status */}
          {isAdmin && (
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Activity className="h-4 w-4 text-muted-foreground" />
                  Configuration
                  {health && (
                    <Badge
                      variant={allOk ? "secondary" : "destructive"}
                      className={
                        allOk ? "bg-green-100 text-green-700 border-green-200 ml-1" : "ml-1"
                      }
                    >
                      {allOk ? "All systems operational" : "Degraded"}
                    </Badge>
                  )}
                </CardTitle>
                <CardDescription>
                  Service health visible to administrators only
                </CardDescription>
              </CardHeader>
              <CardContent>
                {health ? (
                  <div className="space-y-2">
                    {Object.entries(health.checks).map(([svc, status]) => {
                      const meta = SERVICE_DISPLAY[svc] ?? { label: svc, desc: "" };
                      const ok   = status === "ok";
                      return (
                        <div
                          key={svc}
                          className="flex items-center gap-3 rounded-lg border bg-muted/20 px-3 py-2.5"
                        >
                          {ok ? (
                            <CheckCircle2 className="h-4 w-4 shrink-0 text-green-500" />
                          ) : (
                            <XCircle className="h-4 w-4 shrink-0 text-destructive" />
                          )}
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-foreground">{meta.label}</p>
                            <p className="text-xs text-muted-foreground">{meta.desc}</p>
                          </div>
                          <Badge
                            variant={ok ? "secondary" : "destructive"}
                            className={
                              ok
                                ? "text-[10px] bg-green-100 text-green-700"
                                : "text-[10px]"
                            }
                          >
                            {ok ? "Online" : "Offline"}
                          </Badge>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <Activity className="h-4 w-4 animate-pulse" />
                    Checking services...
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Security note */}
          <div className="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 dark:border-amber-800 dark:bg-amber-950/20 px-4 py-3 text-xs text-amber-800 dark:text-amber-300">
            <Shield className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
            <p>
              All queries are processed securely and responses are AI-generated. Always verify
              clinical information with authoritative sources before patient application.
            </p>
          </div>

        </div>
      </div>
    </div>
  );
}
