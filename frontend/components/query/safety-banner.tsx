import { AlertTriangle, ShieldAlert, Info } from "lucide-react";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import type { SafetyFlag } from "@/lib/types";

interface SafetyBannerProps {
  flags:              SafetyFlag[];
  requiresEscalation: boolean;
  escalationReason?:  string | null;
}

const SEVERITY_ORDER: Record<string, number> = {
  critical: 0,
  high:     1,
  medium:   2,
  low:      3,
};

const SEVERITY_BADGE: Record<string, "destructive" | "warning" | "secondary"> = {
  critical: "destructive",
  high:     "destructive",
  medium:   "warning",
  low:      "secondary",
};

function FlagIcon({ severity }: { severity: string }) {
  if (severity === "critical" || severity === "high")
    return <ShieldAlert className="h-4 w-4" />;
  return <AlertTriangle className="h-4 w-4" />;
}

export function SafetyBanner({ flags, requiresEscalation, escalationReason }: SafetyBannerProps) {
  if (!requiresEscalation && flags.length === 0) return null;

  const sorted = [...flags].sort(
    (a, b) => (SEVERITY_ORDER[a.severity] ?? 9) - (SEVERITY_ORDER[b.severity] ?? 9),
  );

  return (
    <div className="space-y-2">
      {requiresEscalation && (
        <Alert variant="destructive">
          <ShieldAlert className="h-4 w-4" />
          <AlertTitle>Clinical Escalation Required</AlertTitle>
          <AlertDescription>
            {escalationReason ??
              "This query requires review by a senior clinician before clinical application."}
          </AlertDescription>
        </Alert>
      )}

      {sorted.map((flag, idx) => (
        <Alert key={idx} variant={flag.severity === "medium" || flag.severity === "low" ? "warning" : "destructive"}>
          <FlagIcon severity={flag.severity} />
          <AlertTitle className="flex items-center gap-2">
            <span className="capitalize">{flag.flag_type.replace(/_/g, " ")}</span>
            <Badge variant={SEVERITY_BADGE[flag.severity] ?? "secondary"} className="text-[10px]">
              {flag.severity}
            </Badge>
          </AlertTitle>
          <AlertDescription>{flag.description}</AlertDescription>
        </Alert>
      ))}
    </div>
  );
}
