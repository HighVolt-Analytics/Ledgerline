import { useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { DashboardFilters, DashboardView } from "@/components/dashboard/DashboardView";
import { useAuth } from "@/context/AuthContext";
import { usePositionLiquidity } from "@/hooks/usePositionLiquidity";
import {
  DASHBOARD_PERIOD_OPTIONS,
  DEFAULT_DASHBOARD_PERIOD,
  type DashboardPeriod,
} from "@/lib/dashboardPeriod";

function dashboardSubtitle(
  user: { is_support_session?: boolean; tenant_name: string },
  period: DashboardPeriod,
  periodLabel?: string
) {
  const windowLabel =
    periodLabel ??
    DASHBOARD_PERIOD_OPTIONS.find((option) => option.value === period)?.label ??
    "Financial year YTD";
  if (user.is_support_session) {
    return `Support view for ${user.tenant_name} · ${windowLabel}`;
  }
  return `Financial overview · ${windowLabel}`;
}

export function DashboardPage() {
  const { user } = useAuth();
  const [period, setPeriod] = useState<DashboardPeriod>(DEFAULT_DASHBOARD_PERIOD);
  const { data: liquidity } = usePositionLiquidity(period);

  const subtitle = useMemo(() => {
    if (!user) return "Financial overview";
    return dashboardSubtitle(user, period, liquidity?.meta.period_label);
  }, [user, period, liquidity?.meta.period_label]);

  return (
    <div>
      <PageHeader
        title="Dashboard"
        subtitle={subtitle}
        actions={<DashboardFilters period={period} onPeriodChange={setPeriod} />}
      />
      <DashboardView tenantName={user?.tenant_name} period={period} />
    </div>
  );
}
