import { Badge } from "@/components/ui/badge";
import type { InvoiceSource } from "@/lib/invoice";
import { invoiceSourceLabel } from "@/lib/invoice";

export function InboxSourceBadge({ kind }: { kind: InvoiceSource }) {
  const label = invoiceSourceLabel(kind);
  return (
    <Badge
      variant="outline"
      className="text-[10px] font-normal border-border text-muted-foreground max-w-full min-w-0 truncate"
      title={label}
    >
      {label}
    </Badge>
  );
}
