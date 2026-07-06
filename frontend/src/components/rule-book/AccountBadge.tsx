import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export function AccountBadge({ account }: { account: string }) {
  const isSuspense = account === "Suspense Account";
  const isUnset = account === "—";
  const warnStyle = isSuspense || isUnset;

  return (
    <Badge
      variant="outline"
      className={cn(
        "font-normal text-[11px] inline-flex items-center gap-1",
        warnStyle
          ? "border-[rgb(var(--system-yellow-rgb)/0.35)] text-foreground"
          : "border-border text-foreground"
      )}
    >
      {isSuspense ? (
        <AlertTriangle className="h-3 w-3 text-destructive shrink-0" aria-hidden />
      ) : null}
      {account}
    </Badge>
  );
}
