import { CaptureSourceLogo } from "@/components/upload/CaptureSourceLogo";
import type { InvoiceSource } from "@/lib/invoice";
import { invoiceSourceLabel } from "@/lib/invoice";

export function InboxSourceBadge({ kind }: { kind: InvoiceSource }) {
  const label = invoiceSourceLabel(kind);
  return (
    <span
      className="inline-flex h-4 w-4 shrink-0 items-center justify-center"
      title={label}
      aria-label={label}
    >
      <CaptureSourceLogo source={kind} />
    </span>
  );
}
