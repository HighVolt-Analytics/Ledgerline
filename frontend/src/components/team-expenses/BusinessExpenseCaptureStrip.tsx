import { useMemo } from "react";
import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";
import { CaptureChannelsStrip } from "@/components/team-expenses/CaptureChannelsStrip";
import type { ClaimChannel } from "@/lib/v4MockData";

export function BusinessExpenseCaptureStrip({
  activeRuleCount = 0,
  enabled = true,
}: {
  activeRuleCount?: number;
  enabled?: boolean;
}) {
  const { data: mailboxes = [], blocked } = useTenantQuery({
    queryKey: queryKeys.mailboxes(),
    queryFn: () => api.listMailboxes(),
    enabled,
  });

  const channels = useMemo((): ClaimChannel[] => {
    const rows: ClaimChannel[] = blocked
      ? []
      : mailboxes.map((mb) => ({
          id: `mb-${mb.id}`,
          name: "Email capture",
          detail: mb.display_name ? `${mb.email} (${mb.display_name})` : mb.email,
          connected: mb.is_active,
        }));

    if (rows.length === 0) {
      rows.push({
        id: "em-default",
        name: "Email capture",
        detail: blocked ? "Loading mailboxes…" : "Connect a mailbox on Integrations",
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
  }, [mailboxes, activeRuleCount, blocked]);

  return <CaptureChannelsStrip channels={channels} testIdPrefix="biz-channel" />;
}
