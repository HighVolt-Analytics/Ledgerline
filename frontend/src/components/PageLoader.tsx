import { Card } from "@/components/ui/card";

export function PageLoader({ label = "Loading…" }: { label?: string }) {
  return (
    <Card className="p-8 text-center text-sm text-muted-foreground animate-pulse">
      {label}
    </Card>
  );
}
