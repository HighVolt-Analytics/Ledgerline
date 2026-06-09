import { Check, X } from "lucide-react";
import { StatusPill, pillTones } from "@/components/StatusPill";
import type { ExpenseState } from "@/lib/v4MockData";

export function ExpenseStateBadge({ state }: { state: ExpenseState }) {
  switch (state) {
    case "New":
      return <StatusPill className={pillTones.amber}>New</StatusPill>;
    case "In Review":
      return <StatusPill className={pillTones.blue}>In Review</StatusPill>;
    case "Approved":
      return (
        <StatusPill className={pillTones.ok}>
          <Check className="h-3 w-3" /> Approved
        </StatusPill>
      );
    case "Rejected":
      return (
        <StatusPill className={pillTones.bad}>
          <X className="h-3 w-3" /> Rejected
        </StatusPill>
      );
    case "Posted to Ledger":
      return (
        <StatusPill className={pillTones.ok}>
          <Check className="h-3 w-3" /> Posted to Ledger
        </StatusPill>
      );
  }
}

export function ChannelBadge({ channel }: { channel: string }) {
  const styles: Record<string, string> = {
    WhatsApp: pillTones.whatsapp,
    Viber: pillTones.amber,
    Web: pillTones.blue,
    Mobile: pillTones.muted,
  };
  return <StatusPill className={styles[channel] ?? pillTones.muted}>{channel}</StatusPill>;
}
