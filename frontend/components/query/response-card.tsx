import { AlertCircle, MessageSquare } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ConfidenceGauge } from "./confidence-gauge";
import { SafetyBanner } from "./safety-banner";
import { CitationList } from "./citation-list";
import { TimingPanel } from "./timing-panel";
import type { QueryResult } from "@/lib/types";

interface ResponseCardProps {
  result: QueryResult;
}

function FormattedResponse({ text }: { text: string }) {
  // Render inline [N] citation markers as styled spans.
  const parts = text.split(/(\[\d+\])/g);
  return (
    <div className="prose prose-sm max-w-none leading-relaxed text-foreground">
      <p>
        {parts.map((part, i) =>
          /^\[\d+\]$/.test(part) ? (
            <span
              key={i}
              className="mx-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-primary/15 text-[11px] font-bold text-primary"
            >
              {part.slice(1, -1)}
            </span>
          ) : (
            <span key={i}>{part}</span>
          ),
        )}
      </p>
    </div>
  );
}

export function ResponseCard({ result }: ResponseCardProps) {
  const hasErrors = result.errors.length > 0;

  return (
    <Card className="response-enter">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2 text-sm font-medium">
          <MessageSquare className="h-4 w-4 text-primary" />
          Clinical Response
        </div>
        <ConfidenceGauge
          score={result.confidence_score}
          cacheHit={result.cache_hit}
          layer={result.cache_layer}
        />
      </CardHeader>

      <CardContent className="space-y-5">
        {/* Error summary */}
        {hasErrors && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>
              Pipeline encountered {result.errors.length} error(s):{" "}
              {result.errors[0]}
              {result.errors.length > 1 && ` (+${result.errors.length - 1} more)`}
            </AlertDescription>
          </Alert>
        )}

        {/* Main answer */}
        <FormattedResponse text={result.final_response} />

        {/* Safety flags + escalation */}
        {(result.safety_flags.length > 0 || result.requires_escalation) && (
          <>
            <Separator />
            <SafetyBanner
              flags={result.safety_flags}
              requiresEscalation={result.requires_escalation}
              escalationReason={result.escalation_reason}
            />
          </>
        )}

        {/* Citations */}
        {result.citations.length > 0 && (
          <>
            <Separator />
            <CitationList citations={result.citations} />
          </>
        )}

        {/* Pipeline timing */}
        <Separator />
        <TimingPanel
          totalMs={result.total_latency_ms}
          agentTimings={result.agent_timings}
          cacheHit={result.cache_hit}
        />
      </CardContent>
    </Card>
  );
}
