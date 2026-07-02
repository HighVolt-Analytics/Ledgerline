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
