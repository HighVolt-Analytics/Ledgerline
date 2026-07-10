import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/skeleton/Skeleton";
import { cn } from "@/lib/cn";

export function KpiGridSkeleton({
  count = 4,
  className,
}: {
  count?: number;
  className?: string;
}) {
  return (
    <div className={cn("grid gap-3 sm:grid-cols-2 lg:grid-cols-4", className)}>
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i} className="p-4 space-y-3">
          <Skeleton className="h-3 w-24" />
          <Skeleton className="h-7 w-16" />
          <Skeleton className="h-9 w-full rounded-md" />
        </Card>
      ))}
    </div>
  );
}

export function ChartCardSkeleton({
  tall = false,
  className,
}: {
  tall?: boolean;
  className?: string;
}) {
  return (
    <Card className={cn("p-4", className)}>
      <div className="flex items-center gap-2 mb-4">
        <Skeleton circle className="h-4 w-4" />
        <Skeleton className="h-4 w-36" />
      </div>
      <Skeleton className={cn("w-full rounded-lg", tall ? "h-48" : "h-40")} />
    </Card>
  );
}

/** Section-only table placeholder — no card chrome; sits inside an existing panel */
export function InlineTableSkeleton({
  rows = 6,
  columns = 6,
  className,
}: {
  rows?: number;
  columns?: number;
  className?: string;
}) {
  return (
    <div className={cn("overflow-hidden", className)} aria-busy aria-label="Loading">
      <div className="px-4 py-2.5 border-b border-border/60">
        <div className="flex gap-3">
          {Array.from({ length: columns }).map((_, i) => (
            <Skeleton key={i} className="h-3 flex-1 max-w-[5.5rem]" />
          ))}
        </div>
      </div>
      <div className="divide-y divide-border/60">
        {Array.from({ length: rows }).map((_, row) => (
          <div key={row} className="flex items-center gap-3 px-4 py-3">
            {Array.from({ length: columns }).map((_, col) => (
              <Skeleton
                key={col}
                className={cn(
                  "h-3.5 flex-1",
                  col === 0 ? "max-w-[7rem]" : col === columns - 1 ? "max-w-[3.5rem]" : "max-w-[4.5rem]"
                )}
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Stacked list rows inside an existing card section */
export function InlineListSkeleton({
  rows = 5,
  className,
}: {
  rows?: number;
  className?: string;
}) {
  return (
    <ul className={cn("divide-y divide-border/60", className)} aria-busy aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className="px-4 py-3 space-y-2">
          <Skeleton className="h-3.5 w-2/5 max-w-[12rem]" />
          <Skeleton className="h-3 w-1/4 max-w-[8rem]" />
        </li>
      ))}
    </ul>
  );
}

export function TableSkeleton({
  rows = 6,
  columns = 5,
  className,
}: {
  rows?: number;
  columns?: number;
  className?: string;
}) {
  return (
    <Card className={cn("overflow-hidden", className)}>
      <div className="px-4 py-3 border-b border-border flex items-center justify-between gap-3">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-9 w-44 rounded-md" />
      </div>
      <div className="px-4 py-2 border-b border-border/60">
        <div className="flex gap-4">
          {Array.from({ length: columns }).map((_, i) => (
            <Skeleton key={i} className="h-3 flex-1 max-w-[6rem]" />
          ))}
        </div>
      </div>
      <div className="divide-y divide-border/60">
        {Array.from({ length: rows }).map((_, row) => (
          <div key={row} className="flex items-center gap-4 px-4 py-3">
            {Array.from({ length: columns }).map((_, col) => (
              <Skeleton
                key={col}
                className={cn("h-3.5 flex-1", col === 0 ? "max-w-[8rem]" : "max-w-[5rem]")}
              />
            ))}
          </div>
        ))}
      </div>
    </Card>
  );
}

/** Icon + title/subtitle + action — matches integration / list-row layouts */
export function ListRowSkeleton({ actionWidth = "w-16" }: { actionWidth?: string }) {
  return (
    <div className="flex items-center gap-3 py-3">
      <Skeleton circle className="h-10 w-10 shrink-0" />
      <div className="flex-1 min-w-0 space-y-2">
        <Skeleton className="h-3.5 w-2/5 max-w-[10rem]" />
        <Skeleton className="h-3 w-3/5 max-w-[14rem]" />
      </div>
      <Skeleton pill className={cn("h-8 shrink-0", actionWidth)} />
    </div>
  );
}

export function IntegrationGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="integration-grid">
      {Array.from({ length: count }).map((_, i) => (
        <Card key={i} className="p-5 space-y-3 min-h-[8.75rem]">
          <div className="flex items-start justify-between gap-2">
            <Skeleton circle className="h-10 w-10" />
            <Skeleton pill className="h-5 w-20" />
          </div>
          <Skeleton className="h-4 w-2/3" />
          <Skeleton className="h-3 w-full" />
        </Card>
      ))}
    </div>
  );
}

export function TabsSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="flex gap-4 border-b border-border pb-2 mb-4">
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className="h-4 w-20" />
      ))}
    </div>
  );
}

export function KanbanBoardSkeleton() {
  return (
    <div className="approvals-kanban-board">
      {Array.from({ length: 4 }).map((_, col) => (
        <section key={col} className="approvals-kanban-column">
          <div className="approvals-kanban-column__header">
            <Skeleton className="h-3.5 w-20" />
            <Skeleton className="h-3 w-12" />
          </div>
          <div className="approvals-kanban-column__cards">
            {Array.from({ length: col === 0 ? 3 : 2 }).map((__, row) => (
              <div key={row} className="approvals-kanban-card pointer-events-none">
                <Skeleton className="h-3.5 w-3/4 mb-2" />
                <Skeleton className="h-3 w-1/2 mb-3" />
                <div className="flex gap-1.5">
                  <Skeleton className="h-[1.375rem] w-14 rounded-md" />
                  <Skeleton className="h-[1.375rem] w-16 rounded-md" />
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

export function RoutedPanelSkeleton() {
  return (
    <Card className="overflow-hidden">
      <div className="px-4 py-3 border-b border-border space-y-2">
        <Skeleton className="h-4 w-48" />
        <Skeleton className="h-3 w-full max-w-md" />
      </div>
      <div className="px-4 py-8">
        <Card className="px-12 py-14 space-y-3">
          <Skeleton className="h-4 w-44 mx-auto" />
          <Skeleton className="h-3 w-full max-w-sm mx-auto" />
        </Card>
      </div>
    </Card>
  );
}

export function CaptureStripSkeleton() {
  return (
    <Card className="p-4 mb-5 space-y-3">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-20 w-full rounded-lg" />
    </Card>
  );
}

export function ListDetailSkeleton({ listRows = 5 }: { listRows?: number }) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <Card className="p-3 space-y-2">
        <Skeleton className="h-9 w-full rounded-md mb-2" />
        {Array.from({ length: listRows }).map((_, i) => (
          <div key={i} className="rounded-lg border border-border p-3 space-y-2">
            <Skeleton className="h-3.5 w-2/3" />
            <Skeleton className="h-3 w-1/2" />
            <div className="flex gap-2">
              <Skeleton pill className="h-5 w-14" />
              <Skeleton pill className="h-5 w-16" />
            </div>
          </div>
        ))}
      </Card>
      <Card className="p-6 space-y-4 min-h-[16rem]">
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-4/5" />
        <Skeleton className="h-24 w-full rounded-lg" />
      </Card>
    </div>
  );
}

export function DashboardPageSkeleton() {
  return (
    <div className="space-y-3">
      <Card className="p-4 mb-1">
        <Skeleton className="h-4 w-64" />
      </Card>
      <KpiGridSkeleton className="mb-3" />
      <KpiGridSkeleton className="mb-6" />
      <div className="grid gap-4 lg:grid-cols-3 mb-6">
        <ChartCardSkeleton tall className="lg:col-span-2" />
        <ChartCardSkeleton />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4 space-y-3">
          <Skeleton className="h-4 w-28" />
          {Array.from({ length: 5 }).map((_, i) => (
            <ListRowSkeleton key={i} actionWidth="w-12" />
          ))}
        </Card>
        <Card className="p-4 space-y-3">
          <Skeleton className="h-4 w-32" />
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center justify-between gap-3 py-2">
              <Skeleton className="h-3.5 flex-1 max-w-[12rem]" />
              <Skeleton pill className="h-5 w-14" />
            </div>
          ))}
        </Card>
      </div>
    </div>
  );
}

export function ReportsPageSkeleton() {
  return (
    <div className="space-y-4">
      <KpiGridSkeleton count={4} className="mb-2" />
      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCardSkeleton tall />
        <ChartCardSkeleton tall />
      </div>
      <TableSkeleton rows={5} columns={4} />
    </div>
  );
}

export function KpiTabsPageSkeleton() {
  return (
    <div className="space-y-5">
      <CaptureStripSkeleton />
      <KpiGridSkeleton />
      <RoutedPanelSkeleton />
      <TabsSkeleton count={2} />
      <ListDetailSkeleton />
    </div>
  );
}

export function UploadPageSkeleton() {
  return (
    <div className="space-y-5">
      <Card className="p-6 space-y-3">
        <Skeleton className="h-4 w-36" />
        <Skeleton className="h-28 w-full rounded-xl border-2 border-dashed border-border bg-muted/20" />
      </Card>
      <Card className="p-4 space-y-3">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-10 w-full rounded-md" />
      </Card>
      <TableSkeleton rows={8} columns={6} />
    </div>
  );
}

export function IntegrationsPageSkeleton() {
  return (
    <div className="space-y-6">
      <IntegrationGridSkeleton />
      <Card className="p-5 space-y-4">
        <div className="space-y-2">
          <Skeleton className="h-4 w-52" />
          <Skeleton className="h-3 w-full max-w-xl" />
        </div>
        <Skeleton className="h-9 w-full max-w-xl rounded-md" />
        <Skeleton className="h-9 w-full max-w-xl rounded-md" />
        <Skeleton pill className="h-8 w-32" />
        {Array.from({ length: 3 }).map((_, i) => (
          <ListRowSkeleton key={i} />
        ))}
      </Card>
    </div>
  );
}

export function BillingPageSkeleton() {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="p-6 space-y-4">
        <Skeleton className="h-5 w-40" />
        <Skeleton className="h-10 w-28" />
        <Skeleton className="h-3 w-full" />
        <Skeleton pill className="h-9 w-36" />
      </Card>
      <Card className="p-6 space-y-3">
        <Skeleton className="h-5 w-32" />
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex justify-between gap-4 py-2 border-b border-border/50 last:border-0">
            <Skeleton className="h-3.5 flex-1 max-w-[12rem]" />
            <Skeleton className="h-3.5 w-10" />
          </div>
        ))}
      </Card>
    </div>
  );
}

export function RulesPageSkeleton() {
  return (
    <div className="space-y-4">
      <TabsSkeleton count={8} />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <Card className="p-5 space-y-4 min-h-[20rem]">
          <Skeleton className="h-5 w-40" />
          <Skeleton className="h-9 w-full rounded-md" />
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="rounded-lg border border-border p-4 space-y-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-3 w-2/3" />
            </div>
          ))}
        </Card>
        <Card className="p-5 space-y-3">
          <Skeleton className="h-5 w-32" />
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-3 w-full" />
          ))}
        </Card>
      </div>
    </div>
  );
}

export function VaultPageSkeleton() {
  return (
    <div className="vault-explorer-grid">
      <Card className="p-4 space-y-2 min-h-[16rem]">
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="flex items-center gap-2 py-1.5">
            <Skeleton circle className="h-4 w-4" />
            <Skeleton className="h-3 flex-1 max-w-[8rem]" />
          </div>
        ))}
      </Card>
      <TableSkeleton rows={7} columns={4} />
    </div>
  );
}

export function WalletCardSkeleton() {
  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <Skeleton className="h-3 w-24" />
        <Skeleton circle className="h-4 w-4" />
      </div>
      <Skeleton className="h-7 w-28" />
      <Skeleton className="h-3 w-full max-w-[12rem]" />
      <div className="flex gap-2 pt-1">
        <Skeleton pill className="h-7 w-20" />
        <Skeleton pill className="h-7 w-24" />
      </div>
    </Card>
  );
}

export function LedgerOverviewSkeleton() {
  return (
    <div className="space-y-4">
      <KpiGridSkeleton count={3} className="sm:grid-cols-3" />
      <Card className="p-4 space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="flex items-center justify-between gap-3 py-2 border-b border-border/50 last:border-0">
            <Skeleton className="h-3.5 w-32" />
            <Skeleton className="h-3.5 w-16" />
          </div>
        ))}
      </Card>
    </div>
  );
}

export function CreationsVendorsTabSkeleton() {
  return (
    <div className="space-y-4" data-testid="vendors-tab-skeleton" aria-busy aria-label="Loading vendors">
      <Card className="p-3 space-y-2">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-3 w-full max-w-xl" />
      </Card>
      <Skeleton className="h-4 w-full max-w-2xl" />
      <Card className="p-4 space-y-4">
        <Skeleton className="h-4 w-44" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <Skeleton key={i} className="h-8 w-full rounded-md" />
          ))}
        </div>
        <Skeleton className="h-8 w-full max-w-xs rounded-md" />
      </Card>
      <Card className="overflow-hidden p-0">
        <div className="border-b border-border/60 p-3">
          <div className="flex flex-wrap gap-2">
            <Skeleton className="h-8 flex-1 min-w-[200px] rounded-md" />
            <Skeleton className="h-8 w-40 rounded-md" />
            <Skeleton pill className="h-8 w-28" />
          </div>
        </div>
        <InlineTableSkeleton rows={6} columns={7} />
      </Card>
    </div>
  );
}

export function CreationsEmployeesTabSkeleton() {
  return (
    <div className="space-y-4" data-testid="employees-tab-skeleton" aria-busy aria-label="Loading employees">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Skeleton className="h-4 w-full max-w-2xl" />
        <div className="flex gap-2">
          <Skeleton pill className="h-8 w-24" />
          <Skeleton pill className="h-8 w-32" />
        </div>
      </div>
      <Card className="overflow-hidden p-0">
        <InlineTableSkeleton rows={6} columns={6} />
      </Card>
      <Card className="overflow-hidden p-0">
        <div className="border-b border-border/60 p-3">
          <Skeleton className="h-4 w-44" />
        </div>
        <InlineTableSkeleton rows={4} columns={4} />
      </Card>
    </div>
  );
}

export function GenericPageSkeleton() {
  return (
    <div className="space-y-4">
      <KpiGridSkeleton count={3} className="max-w-3xl" />
      <Card className="p-5 space-y-3">
        {Array.from({ length: 4 }).map((_, i) => (
          <ListRowSkeleton key={i} />
        ))}
      </Card>
    </div>
  );
}
