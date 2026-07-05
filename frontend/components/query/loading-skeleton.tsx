import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent, CardHeader } from "@/components/ui/card";

export function ResponseSkeleton() {
  return (
    <Card>
      <CardHeader className="pb-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-full" />
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Response body */}
        <div className="space-y-2">
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-5/6" />
          <Skeleton className="h-3 w-4/6" />
          <Skeleton className="h-3 w-full" />
          <Skeleton className="h-3 w-3/4" />
        </div>
        {/* Citations */}
        <div className="space-y-2 pt-4">
          <Skeleton className="h-3 w-24" />
          {[1, 2, 3].map((i) => (
            <div key={i} className="flex gap-3 rounded-lg border p-3">
              <Skeleton className="h-5 w-5 rounded-full shrink-0" />
              <div className="flex-1 space-y-1.5">
                <Skeleton className="h-3 w-20" />
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-3/4" />
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
