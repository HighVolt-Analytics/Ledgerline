import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export function InboxGlAccountBadge({ account }: { account: string | null }) {
  if (!account) {
    return <span className="text-muted-foreground">—</span>;
  }
  const suspense = account === "Suspense Account";
  return (
    <Badge
      variant="outline"
      className={cn(
        "font-normal",
        suspense ? "border-destructive/40 text-destructive" : "border-border text-foreground"
      )}
    >
      {account}
    </Badge>
  );
}
