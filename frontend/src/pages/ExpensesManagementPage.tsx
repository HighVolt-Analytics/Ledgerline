import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { ListDetailSkeleton } from "@/components/skeleton/PageSkeletons";
import { LazyInvoiceDetailDrawer } from "@/components/LazyInvoiceDetailDrawer";
import { KpiCard } from "@/components/KpiCard";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { BusinessExpenseCaptureStrip } from "@/components/team-expenses/BusinessExpenseCaptureStrip";
import { ClaimDetailPanel } from "@/components/team-expenses/ClaimDetailPanel";
import { ChannelBadge, ExpenseStateBadge } from "@/components/team-expenses/ExpenseBadges";
import { RoutedInvoicesPanel } from "@/components/rule-book/RoutedInvoicesPanel";
import { Card } from "@/components/ui/card";
import { useExpenseClaimActions } from "@/hooks/useExpenseClaimActions";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useRoutedInvoices } from "@/hooks/useRoutedInvoices";
import { useInstitutionSettings } from "@/hooks/useInstitutionSettings";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { cn } from "@/lib/cn";
import { matchesListSearch } from "@/lib/listSearch";
import { formatMoneyByCurrencyMap, money } from "@/lib/format";
import { expenseRulesToCategories, invoiceToBusinessExpense } from "@/lib/routePageAdapters";

const ROUTE_TARGET = "Expenses Management";
const CLAIM_POLL_MS = 15_000;

export function ExpensesManagementPage() {
  const { data: routed = [], isLoading, refetch } = useRoutedInvoices(ROUTE_TARGET);
  const { data: ruleBook } = useRuleBookConfig();
  const { data: institution } = useInstitutionSettings();
  const institutionCurrency = (institution?.currency || "SGD").trim().toUpperCase() || "SGD";
  const actions = useExpenseClaimActions(ROUTE_TARGET);

  const claims = useMemo(() => routed.map(invoiceToBusinessExpense), [routed]);
  const invoiceById = useMemo(() => new Map(routed.map((inv) => [inv.id, inv])), [routed]);
  const categories = useMemo(
    () => expenseRulesToCategories(ruleBook?.expenseRules ?? []),
    [ruleBook?.expenseRules]
  );
  const activeRuleCount = useMemo(
    () => (ruleBook?.expenseRules ?? []).filter((r) => r.enabled).length,
    [ruleBook?.expenseRules]
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const [tab, setTab] = useState("expenses");
  const [searchQuery, setSearchQuery] = useState("");

  useVisibilityPolling(() => {
    void refetch();
  }, CLAIM_POLL_MS);

  useEffect(() => {
    if (!actions.toast) return;
    const t = setTimeout(() => actions.setToast(null), 3000);
    return () => clearTimeout(t);
  }, [actions.toast, actions.setToast]);

  const kpis = useMemo(() => {
    const open = claims.filter((e) => e.state === "New" || e.state === "In Review").length;
    const postedInvoices = routed.filter(
      (inv) => inv.status === "processed" && inv.published_to_ledger
    );
    const postedByCurrency: Record<string, number> = {};
    for (const inv of postedInvoices) {
      const code = (inv.currency || institutionCurrency).trim().toUpperCase() || institutionCurrency;
      postedByCurrency[code] =
        (postedByCurrency[code] ?? 0) + (parseFloat(String(inv.total ?? 0)) || 0);
    }
    const pending = claims.filter((e) => e.state === "In Review").length;
    return { open, postedCount: postedInvoices.length, postedByCurrency, pending };
  }, [claims, routed, institutionCurrency]);

  const selected = claims.find((e) => e.id === selectedId) ?? claims[0] ?? null;
  const filteredClaims = useMemo(
    () =>
      claims.filter((claim) =>
        matchesListSearch(
          searchQuery,
          claim.id,
          claim.documentRef,
          claim.merchant,
          claim.category,
          claim.state,
          claim.channel,
          claim.amount,
          claim.date
        )
      ),
    [claims, searchQuery]
  );
  const selectedInvoice = selected ? invoiceById.get(Number(selected.id)) : undefined;

  return (
    <div>
      {actions.toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md max-w-sm">
          {actions.toast}
        </div>
      )}

      <PageHeader
        title="Expenses Management"
        subtitle="Non-PO business expenses — utilities, subscriptions, and professional services routed by expense rules."
      />

      <BusinessExpenseCaptureStrip activeRuleCount={activeRuleCount} />

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-5">
        <KpiCard label="Open expenses" value={isLoading ? "…" : kpis.open} testid="kpi-biz-open" />
        <KpiCard
          label="Posted this month"
          value={isLoading ? "…" : formatMoneyByCurrencyMap(kpis.postedByCurrency)}
          testid="kpi-biz-posted"
          delta={
            !isLoading && kpis.postedCount > 0
              ? { dir: "up", text: `${kpis.postedCount} posted`, good: true }
              : undefined
          }
        />
        <KpiCard
          label="In review"
          value={isLoading ? "…" : kpis.pending}
          testid="kpi-biz-review"
        />
        <KpiCard
          label="Rule categories"
          value={isLoading ? "…" : categories.length}
          testid="kpi-biz-categories"
        />
      </div>

      <RoutedInvoicesPanel
        routeTarget={ROUTE_TARGET}
        title="Documents routed from Rule Book"
        hint="Invoices routed to Expenses Management after OCR and document classification."
        testId="expenses-routed-invoices"
      />

      <PageTabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "expenses", label: "Expenses", testid: "tab-biz-expenses" },
          { value: "categories", label: "Categories", testid: "tab-biz-categories" },
        ]}
        className="mt-5"
      />

      <PageTabPanel value="expenses" active={tab} className="mt-4">
        {isLoading ? (
          <ListDetailSkeleton />
        ) : claims.length === 0 ? (
          <EmptyState
            title="No business expenses yet"
            hint="Documents routed to Expenses Management appear here after capture or rule-book remap."
          />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <div className="space-y-2 lg:max-h-[calc(100dvh-360px)] lg:overflow-y-auto lg:pr-1">
              <ListSearchInput
                value={searchQuery}
                onChange={setSearchQuery}
                placeholder="Search this list…"
                testId="input-biz-expenses-search"
                className="sticky top-0 z-10 bg-background pb-2"
              />
              {filteredClaims.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">
                  No expenses match your search.
                </p>
              ) : null}
              {filteredClaims.map((claim) => (
                <button
                  key={claim.id}
                  type="button"
                  onClick={() => setSelectedId(claim.id)}
                  data-testid={`biz-expense-${claim.id}`}
                  className={cn(
                    "w-full text-left rounded-lg border p-3 transition-colors hover-elevate",
                    selected?.id === claim.id
                      ? "border-primary bg-primary/5"
                      : "border-border bg-card"
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="font-medium text-sm truncate">{claim.merchant}</div>
                      <div className="text-xs text-muted-foreground mt-0.5 truncate">
                        {claim.category} · {claim.date}
                      </div>
                      {claim.documentRef ? (
                        <div className="text-[10px] text-muted-foreground tnum mt-0.5 truncate">
                          {claim.documentRef}
                        </div>
                      ) : null}
                    </div>
                    <div className="text-right shrink-0">
                      <div className="tnum font-semibold text-sm">
                        {money(
                          claim.amount,
                          invoiceById.get(Number(claim.id))?.currency || institutionCurrency
                        )}
                      </div>
                      <div className="text-[10px] text-muted-foreground">{claim.submittedTs}</div>
                    </div>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <ExpenseStateBadge state={claim.state} />
                    <ChannelBadge channel={claim.channel} />
                  </div>
                </button>
              ))}
            </div>

            <div>
              {selected && selectedInvoice ? (
                <Card className="p-4">
                  <ClaimDetailPanel
                    key={selected.id}
                    claim={selected}
                    invoiceId={selectedInvoice.id}
                    invoiceStatus={selectedInvoice.status}
                    hasStoredFile={selectedInvoice.has_stored_file}
                    busy={actions.busyId === selectedInvoice.id}
                    canApprove={actions.canApproveClaim(selectedInvoice.status)}
                    canReject={actions.canRejectClaim(selectedInvoice.status)}
                    canRequestInfo={actions.canRequestInfo(selectedInvoice.status)}
                    currency={
                      (selectedInvoice.currency || institutionCurrency).trim().toUpperCase() ||
                      institutionCurrency
                    }
                    onApprove={async () => {
                      await actions.approve(selectedInvoice);
                    }}
                    onReject={async () => {
                      await actions.reject(selectedInvoice);
                    }}
                    onRequestInfo={async () => {
                      await actions.requestInfo(selectedInvoice);
                    }}
                    onOpenInvoice={() => setDrawerInvoiceId(selectedInvoice.id)}
                  />
                </Card>
              ) : (
                <EmptyState
                  title="Select an expense"
                  hint="Choose an expense from the list to review its detail."
                />
              )}
            </div>
          </div>
        )}
      </PageTabPanel>

      <PageTabPanel value="categories" active={tab} className="mt-4">
        {categories.length === 0 ? (
          <EmptyState
            title="No expense categories configured"
            hint="Enable expense rules on the Rule Book → Expenses tab."
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {categories.map((cat) => (
              <Card key={cat.category} className="p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{cat.category}</span>
                  <span className="text-xs text-muted-foreground">{cat.glAccount}</span>
                </div>
                <p className="text-xs text-muted-foreground">{cat.policyNote}</p>
              </Card>
            ))}
          </div>
        )}
      </PageTabPanel>

      <LazyInvoiceDetailDrawer
        invoiceId={drawerInvoiceId}
        open={drawerInvoiceId != null}
        onClose={() => setDrawerInvoiceId(null)}
        onUpdated={() => void refetch()}
      />
    </div>
  );
}
