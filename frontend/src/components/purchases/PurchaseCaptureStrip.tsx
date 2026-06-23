import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { CaptureChannelsStrip } from "@/components/team-expenses/CaptureChannelsStrip";
import type { ClaimChannel } from "@/lib/v4MockData";

export function PurchaseCaptureStrip({ activeRuleCount = 0 }: { activeRuleCount?: number }) {
  const { data: mailboxes = [] } = useQuery({
    queryKey: ["mailboxes"],
    queryFn: () => api.listMailboxes(),
  });

  const channels = useMemo((): ClaimChannel[] => {
    const rows: ClaimChannel[] = mailboxes.map((mb) => ({
      id: `mb-${mb.id}`,
      name: "Email capture",
      detail: mb.display_name ? `${mb.email} (${mb.display_name})` : mb.email,
      connected: mb.is_active,
    }));

    if (rows.length === 0) {
      rows.push({
        id: "em-default",
        name: "Email capture",
        detail: "Connect a mailbox on Integrations",
        connected: false,
      });
    }

    if (activeRuleCount > 0) {
      rows.push({
        id: "rules",
        name: "Purchase rules",
        detail: `${activeRuleCount} active PO rule${activeRuleCount === 1 ? "" : "s"}`,
        connected: true,
      });
    }

    return rows;
  }, [mailboxes, activeRuleCount]);

  return <CaptureChannelsStrip channels={channels} testIdPrefix="purchase-channel" />;
}
