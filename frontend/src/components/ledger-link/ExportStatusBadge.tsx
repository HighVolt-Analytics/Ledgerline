import { Check } from "lucide-react";
import { StatusPill, pillTones } from "@/components/StatusPill";

export function ExportStatusBadge({ status }: { status: string }) {
  if (status === "Pending Export") return <StatusPill className={pillTones.muted}>Pending Export</StatusPill>;
  if (status === "Exported") return <StatusPill className={pillTones.blue}>Exported</StatusPill>;
  return (
    <StatusPill className={pillTones.ok}>
      <Check className="h-3 w-3" /> {status}
    </StatusPill>
  );
}
