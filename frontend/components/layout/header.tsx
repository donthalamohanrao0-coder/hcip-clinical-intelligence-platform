import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

interface HeaderProps {
  title:       string;
  description?: string;
  badge?:       string;
}

export function Header({ title, description, badge }: HeaderProps) {
  return (
    <div className="border-b bg-background">
      <div className="flex items-center gap-4 px-6 py-4">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h1 className="text-lg font-semibold">{title}</h1>
            {badge && <Badge variant="secondary">{badge}</Badge>}
          </div>
          {description && (
            <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>
          )}
        </div>
      </div>
      <Separator />
    </div>
  );
}
