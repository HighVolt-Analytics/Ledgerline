import { PageHeader } from "@/components/PageHeader";
import { PageLoader } from "@/components/PageLoader";
import { EmptyState } from "@/components/EmptyState";
import { ReportsCatalog } from "@/components/reports/ReportsCatalog";
import { useReportCatalog } from "@/hooks/useReportCatalog";

export function ReportsPage() {
  const { data, isLoading, error } = useReportCatalog();

  if (isLoading) {
    return (
      <div>
        <PageHeader title="Reports" />
        <PageLoader variant="reports" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div>
        <PageHeader title="Reports" />
        <EmptyState
          title="Could not load reports"
          hint={error instanceof Error ? error.message : "Try again later."}
        />
      </div>
    );
  }

  return (
    <div>
      <ReportsCatalog reports={data.reports} favouriteIds={data.favourite_ids} />
    </div>
  );
}
