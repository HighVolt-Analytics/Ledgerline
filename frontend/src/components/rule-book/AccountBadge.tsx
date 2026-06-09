import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";

export function AccountBadge({ account }: { account: string }) {
  const suspense = account === "Suspense Account" || account === "—";
  return (
    <Badge
      variant="outline"
      className={cn(
        "font-normal text-[11px]",
        suspense
          ? "border-destructive/40 text-destructive"
          : "border-border text-foreground"
      )}
    >
      {account}
    </Badge>
  );
}
