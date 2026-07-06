import { AlertTriangle } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export function InboxGlAccountBadge({
  account,
  glPostingApplicable = true,
}: {
  account: string | null;
  glPostingApplicable?: boolean;
}) {
  if (!glPostingApplicable) {
    return (
      <Badge
        variant="outline"
        className="font-normal border-muted-foreground/30 text-muted-foreground"
      >
        Not posted
      </Badge>
    );
  }
  if (!account) {
    return <span className="text-muted-foreground">—</span>;
  }
  const isSuspense = account === "Suspense Account";
  return (
    <Badge
      variant="outline"
      className={cn(
        "font-normal inline-flex items-center gap-1",
        isSuspense
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
