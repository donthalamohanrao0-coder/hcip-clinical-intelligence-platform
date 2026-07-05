import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { formatConfidence } from "@/lib/utils";
import { cn } from "@/lib/utils";

interface ConfidenceGaugeProps {
  score:    number;
  cacheHit: boolean;
  layer?:   string | null;
}

function confidenceTier(score: number): {
  label:   string;
  variant: "success" | "warning" | "destructive";
  color:   string;
} {
  if (score >= 0.75) return { label: "High Confidence",   variant: "success",     color: "bg-emerald-500" };
  if (score >= 0.50) return { label: "Moderate",          variant: "warning",     color: "bg-amber-500"   };
  return               { label: "Low Confidence",   variant: "destructive", color: "bg-red-500"     };
}

export function ConfidenceGauge({ score, cacheHit, layer }: ConfidenceGaugeProps) {
  const { label, variant, color } = confidenceTier(score);

  return (
    <div className="flex items-center gap-4">
      <div className="flex-1 space-y-1">
        <div className="flex items-center justify-between text-xs">
          <span className="text-muted-foreground">Confidence</span>
          <span className="font-semibold">{formatConfidence(score)}</span>
        </div>
        <div className="relative h-2 w-full overflow-hidden rounded-full bg-secondary">
          <div
            className={cn("h-full rounded-full transition-all", color)}
            style={{ width: `${score * 100}%` }}
          />
        </div>
      </div>

      <div className="flex shrink-0 items-center gap-2">
        <Badge variant={variant}>{label}</Badge>
        {cacheHit && (
          <Badge variant="secondary" className="gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            {layer ? `${layer} cache` : "cached"}
          </Badge>
        )}
      </div>
    </div>
  );
}
