import { Check } from "lucide-react";
import { StatusPill, pillTones } from "@/components/StatusPill";

export function ExportStatusBadge({ status }: { status: string }) {
  if (status === "Pending Export") return <StatusPill className={pillTones.muted}>Pending Export</StatusPill>;
  if (status === "Exported") return <StatusPill className={pillTones.blue}>Exported</StatusPill>;
  if (status === "Sending to Xero") {
    return <StatusPill className={pillTones.muted}>Sending to Xero</StatusPill>;
  }
  if (status.startsWith("Push failed") || status === "Push failed") {
    return <StatusPill className={pillTones.bad}>{status}</StatusPill>;
  }
  if (status.startsWith("Pushed to Xero") || status.startsWith("Pushed to ")) {
    return (
      <StatusPill className={pillTones.ok}>
        <Check className="h-3 w-3" /> {status}
      </StatusPill>
    );
  }
  if (status.startsWith("Skipped")) {
    return <StatusPill className={pillTones.muted}>{status}</StatusPill>;
  }
  return (
    <StatusPill className={pillTones.ok}>
      <Check className="h-3 w-3" /> {status}
    </StatusPill>
  );
}
