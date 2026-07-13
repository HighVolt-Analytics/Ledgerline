import {
  BillingPageSkeleton,
  DashboardPageSkeleton,
  DossierDetailPageSkeleton,
  GenericPageSkeleton,
  IntegrationsPageSkeleton,
  KanbanBoardSkeleton,
  KpiTabsPageSkeleton,
  ReportsPageSkeleton,
  RulesPageSkeleton,
  TableSkeleton,
  UploadPageSkeleton,
  VaultPageSkeleton,
} from "@/components/skeleton/PageSkeletons";

export type PageLoaderVariant =
  | "default"
  | "dashboard"
  | "reports"
  | "kpi-tabs"
  | "table"
  | "integrations"
  | "kanban"
  | "billing"
  | "rules"
  | "vault"
  | "upload"
  | "dossier-detail";

export function PageLoader({
  variant = "default",
}: {
  /** @deprecated Skeleton layouts replace loading labels */
  label?: string;
  variant?: PageLoaderVariant;
}) {
  switch (variant) {
    case "dashboard":
      return <DashboardPageSkeleton />;
    case "reports":
      return <ReportsPageSkeleton />;
    case "kpi-tabs":
      return <KpiTabsPageSkeleton />;
    case "table":
      return <TableSkeleton />;
    case "integrations":
      return <IntegrationsPageSkeleton />;
    case "kanban":
      return <KanbanBoardSkeleton />;
    case "billing":
      return <BillingPageSkeleton />;
    case "rules":
      return <RulesPageSkeleton />;
    case "vault":
      return <VaultPageSkeleton />;
    case "upload":
      return <UploadPageSkeleton />;
    case "dossier-detail":
      return <DossierDetailPageSkeleton />;
    default:
      return <GenericPageSkeleton />;
  }
}
