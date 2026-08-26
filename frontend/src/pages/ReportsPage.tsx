import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { EmptyState } from "@/components/EmptyState";
import { ReportsCatalog } from "@/components/reports/ReportsCatalog";
import { useReportCatalog } from "@/hooks/useReportCatalog";

const REPORTS_SUBTITLE =
  "Payables, budgets, team expenses, and exception reports from the reporting pack.";

export function ReportsPage() {
  const { data, isLoading, error } = useReportCatalog();

  if (isLoading) {
    return (
      <div>
        <PageHeader title="Reports" subtitle={REPORTS_SUBTITLE} />
        <PageLoader variant="reports" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div>
        <PageHeader title="Reports" subtitle={REPORTS_SUBTITLE} />
        <EmptyState
          title="Could not load reports"
          hint={error instanceof Error ? error.message : "Try again later."}
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader title="Reports" subtitle={REPORTS_SUBTITLE} />
      <ReportsCatalog reports={data.reports} favouriteIds={data.favourite_ids} />
    </div>
  );
}
