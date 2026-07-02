import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";
import { CaptureChannelsStrip } from "@/components/team-expenses/CaptureChannelsStrip";
import type { ClaimChannel } from "@/lib/v4MockData";

export function BusinessExpenseCaptureStrip({ activeRuleCount = 0 }: { activeRuleCount?: number }) {
  const { data: mailboxes = [] } = useQuery({
    queryKey: queryKeys.mailboxes(),
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
        name: "Expense rules",
        detail: `${activeRuleCount} active categor${activeRuleCount === 1 ? "y" : "ies"}`,
        connected: true,
      });
    }

    return rows;
  }, [mailboxes, activeRuleCount]);

  return <CaptureChannelsStrip channels={channels} testIdPrefix="biz-channel" />;
}
