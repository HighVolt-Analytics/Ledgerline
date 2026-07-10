import { AlertTriangle, Ban, Check } from "lucide-react";
import { StatusPill, pillTones } from "@/components/StatusPill";
import type { MatrixFlagType } from "@/lib/v4MatrixMockData";

export function MatrixFlagBadge({ flag }: { flag: MatrixFlagType }) {
  if (flag === "Clean") {
    return (
      <StatusPill className={pillTones.ok}>
        <Check className="matrix-ok-icon h-3 w-3 shrink-0" />
        Clean
      </StatusPill>
    );
  }
  if (flag === "Duplicate Suspected") {
    return (
      <StatusPill className="bg-[hsl(340_75%_55%/0.16)] text-[hsl(340_70%_45%)] dark:text-[hsl(340_80%_72%)] border-transparent">
        <AlertTriangle className="h-3 w-3" />
        Duplicate Suspected
      </StatusPill>
    );
  }
  if (flag === "Quarantined") {
    return (
      <StatusPill className={pillTones.bad}>
        <Ban className="h-3 w-3" />
        Quarantined
      </StatusPill>
    );
  }
  return (
    <StatusPill className={pillTones.amber}>
      <AlertTriangle className="h-3 w-3 ds-warning-icon" />
      Anomaly Detected
    </StatusPill>
  );
}
