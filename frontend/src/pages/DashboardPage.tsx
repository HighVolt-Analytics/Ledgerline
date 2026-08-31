import { PageHeader } from "@/components/PageHeader";
import {
  CfoCommandCentre,
  CfoDashboardFilters,
} from "@/components/dashboard/cfo/CfoCommandCentre";
import { useAuth } from "@/context/AuthContext";

function dashboardSubtitle(user: { is_support_session?: boolean; tenant_name: string }) {
  if (user.is_support_session) {
    return `Support view for ${user.tenant_name}. One-page financial command summary.`;
  }
  return "One-page financial command summary — FY26 YTD to 31 Aug 2026";
}

export function DashboardPage() {
  const { user } = useAuth();

  return (
    <div>
      <PageHeader
        title="CFO Command Centre"
        subtitle={user ? dashboardSubtitle(user) : "One-page financial command summary"}
        actions={<CfoDashboardFilters />}
      />
      <CfoCommandCentre tenantName={user?.tenant_name} />
    </div>
  );
}
