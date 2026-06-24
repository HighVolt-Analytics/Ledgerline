import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { InvoiceDetailDrawer } from "@/components/InvoiceDetailDrawer";
import { KpiCard } from "@/components/KpiCard";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { BudgetUtilBar } from "@/components/team-expenses/BudgetUtilBar";
import { ClaimDetailPanel } from "@/components/team-expenses/ClaimDetailPanel";
import { ChannelBadge, ExpenseStateBadge } from "@/components/team-expenses/ExpenseBadges";
import { TeamExpenseChannelsStrip } from "@/components/team-expenses/TeamExpenseChannelsStrip";
import { RoutedInvoicesPanel } from "@/components/rule-book/RoutedInvoicesPanel";
import { Card } from "@/components/ui/card";
import { useEmployeeMasters } from "@/hooks/useMasterData";
import { useExpenseClaimActions } from "@/hooks/useExpenseClaimActions";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useRoutedInvoices } from "@/hooks/useRoutedInvoices";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { cn } from "@/lib/cn";
import { matchesListSearch } from "@/lib/listSearch";
import { money } from "@/lib/format";
import {
  employeeBudgetRows,
  invoiceToTeamClaim,
  teamRulesToCategories,
} from "@/lib/routePageAdapters";
import { fmtAud } from "@/lib/v4MockData";

const ROUTE_TARGET = "Team Expenses";
const CLAIM_POLL_MS = 15_000;

function initials(name: string) {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

export function TeamExpensesPage() {
  const { data: routed = [], isLoading, refetch } = useRoutedInvoices(ROUTE_TARGET);
  const { data: employees = [] } = useEmployeeMasters();
  const { data: ruleBook } = useRuleBookConfig();
  const actions = useExpenseClaimActions(ROUTE_TARGET);

  const claims = useMemo(() => routed.map(invoiceToTeamClaim), [routed]);
  const invoiceById = useMemo(() => new Map(routed.map((inv) => [inv.id, inv])), [routed]);
  const budgets = useMemo(() => employeeBudgetRows(employees), [employees]);
  const categories = useMemo(
    () => teamRulesToCategories(ruleBook?.teamExpenseRules ?? []),
    [ruleBook?.teamExpenseRules]
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drawerInvoiceId, setDrawerInvoiceId] = useState<number | null>(null);
  const [tab, setTab] = useState("claims");
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
    const postedTotal = postedInvoices.reduce(
      (s, inv) => s + (parseFloat(String(inv.total ?? 0)) || 0),
      0
    );
    const pending = claims.filter((e) => e.state === "In Review").length;
    const teamBudgets = budgets.filter((b) => b.period === "Monthly" && b.category === "All categories");
    const totalBudget = teamBudgets.reduce((s, b) => s + b.monthlyBudget, 0);
    const totalUsed = teamBudgets.reduce((s, b) => s + b.used, 0);
    const util = totalBudget > 0 ? Math.round((totalUsed / totalBudget) * 100) : 0;
    return { open, postedCount: postedInvoices.length, postedTotal, pending, util };
  }, [claims, budgets, routed]);

  const selected = claims.find((e) => e.id === selectedId) ?? claims[0] ?? null;
  const filteredClaims = useMemo(
    () =>
      claims.filter((claim) =>
        matchesListSearch(
          searchQuery,
          claim.id,
          claim.documentRef,
          claim.submitter,
          claim.category,
          claim.merchant,
          claim.state,
          claim.channel,
          claim.amount
        )
      ),
    [claims, searchQuery]
  );
  const selectedInvoice = selected ? invoiceById.get(Number(selected.id)) : undefined;
  const budget = selected
    ? budgets.find((b) => b.owner !== "Team" && b.category === selected.category)
    : undefined;

  return (
    <div>
      {actions.toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md max-w-sm">
          {actions.toast}
        </div>
      )}

      <PageHeader
        title="Team Expenses"
        subtitle="Employee claims captured from messaging channels, approved against per-category budgets, posted to the ledger."
      />

      <TeamExpenseChannelsStrip />

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-5">
        <KpiCard
          label="Open Claims"
          value={isLoading ? "…" : kpis.open}
          testid="kpi-exp-open"
        />
        <KpiCard
          label="Posted This Month"
          value={isLoading ? "…" : fmtAud(kpis.postedTotal)}
          testid="kpi-exp-approved"
          delta={
            !isLoading && kpis.postedCount > 0
              ? { dir: "up", text: `${kpis.postedCount} claims`, good: true }
              : undefined
          }
        />
        <KpiCard
          label="Budget Utilised"
          value={isLoading ? "…" : `${kpis.util}%`}
          testid="kpi-exp-util"
        />
        <KpiCard
          label="Pending Approval"
          value={isLoading ? "…" : kpis.pending}
          testid="kpi-exp-pending"
        />
      </div>

      <RoutedInvoicesPanel
        routeTarget={ROUTE_TARGET}
        title="Documents routed from Rule Book"
        hint="Employee expense claims routed here after OCR and document classification."
        testId="team-routed-invoices"
      />

      <PageTabs
        value={tab}
        onChange={setTab}
        tabs={[
          { value: "claims", label: "Claims", testid: "tab-claims" },
          { value: "budgets", label: "Budgets", testid: "tab-budgets" },
          { value: "categories", label: "Categories", testid: "tab-categories" },
        ]}
      />

      <PageTabPanel value="claims" active={tab} className="mt-4">
        {isLoading ? (
          <div className="text-sm text-muted-foreground py-8">Loading team expense claims…</div>
        ) : claims.length === 0 ? (
          <EmptyState
            title="No team expense claims yet"
            hint="Documents routed to Team Expenses appear here after OCR and rule-book evaluation."
          />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <div className="space-y-2 lg:max-h-[calc(100dvh-360px)] lg:overflow-y-auto lg:pr-1">
              <ListSearchInput
                value={searchQuery}
                onChange={setSearchQuery}
                placeholder="Search this list…"
                testId="input-team-claims-search"
                className="sticky top-0 z-10 bg-background pb-2"
              />
              {filteredClaims.length === 0 ? (
                <p className="text-sm text-muted-foreground text-center py-6">
                  No claims match your search.
                </p>
              ) : null}
              {filteredClaims.map((claim) => (
                <button
                  key={claim.id}
                  type="button"
                  onClick={() => setSelectedId(claim.id)}
                  data-testid={`claim-${claim.id}`}
                  className={cn(
                    "w-full text-left rounded-lg border p-3 transition-colors hover-elevate",
                    selected?.id === claim.id
                      ? "border-primary bg-primary/5"
                      : "border-border bg-card"
                  )}
                >
                  <div className="flex items-start gap-3">
                    <div className="h-10 w-10 rounded-md bg-primary/10 text-primary flex items-center justify-center text-xs font-semibold shrink-0">
                      {initials(claim.submitter)}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm truncate">{claim.submitter}</span>
                        <ChannelBadge channel={claim.channel} />
                      </div>
                      <div className="text-xs text-muted-foreground truncate mt-0.5">
                        {claim.category} · {claim.merchant}
                      </div>
                      {claim.documentRef ? (
                        <div className="text-[10px] text-muted-foreground tnum mt-0.5 truncate">
                          {claim.documentRef}
                        </div>
                      ) : null}
                    </div>
                    <div className="text-right shrink-0">
                      <div className="tnum font-semibold text-sm">{fmtAud(claim.amount)}</div>
                      <div className="text-[10px] text-muted-foreground">{claim.submittedTs}</div>
                    </div>
                  </div>
                  <div className="mt-2">
                    <ExpenseStateBadge state={claim.state} />
                  </div>
                </button>
              ))}
            </div>

            <div>
              {selected && selectedInvoice ? (
                <Card className="p-4">
                  <ClaimDetailPanel
                    claim={selected}
                    invoiceId={selectedInvoice.id}
                    invoiceStatus={selectedInvoice.status}
                    hasStoredFile={selectedInvoice.has_stored_file}
                    budget={budget}
                    busy={actions.busyId === selectedInvoice.id}
                    canApprove={actions.canApproveClaim(selectedInvoice.status)}
                    canReject={actions.canRejectClaim(selectedInvoice.status)}
                    canRequestInfo={actions.canRequestInfo(selectedInvoice.status)}
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
                  title="Select a claim"
                  hint="Choose a claim from the feed to review its detail."
                />
              )}
            </div>
          </div>
        )}
      </PageTabPanel>

      <PageTabPanel value="budgets" active={tab} className="mt-4">
        {budgets.length === 0 ? (
          <EmptyState
            title="No employee budgets configured"
            hint="Add employees with budget caps on the Rule Book → Employees tab."
          />
        ) : (
          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b border-border text-left">
                    <th className="px-4 py-2.5 font-medium">Category</th>
                    <th className="px-3 py-2.5 font-medium">Employee</th>
                    <th className="px-3 py-2.5 font-medium">Period</th>
                    <th className="px-3 py-2.5 font-medium text-right">Budget</th>
                    <th className="px-3 py-2.5 font-medium text-right">Used</th>
                    <th className="px-3 py-2.5 font-medium text-right">Remaining</th>
                    <th className="px-4 py-2.5 font-medium w-44">Utilisation</th>
                  </tr>
                </thead>
                <tbody>
                  {budgets.map((row, idx) => {
                    const remaining = row.monthlyBudget - row.used;
                    const pct =
                      row.monthlyBudget > 0
                        ? Math.round((row.used / row.monthlyBudget) * 100)
                        : 0;
                    return (
                      <tr key={idx} className="row-band border-b border-border/60">
                        <td className="px-4 py-2.5 font-medium">{row.category}</td>
                        <td className="px-3 py-2.5 text-muted-foreground">{row.owner}</td>
                        <td className="px-3 py-2.5 text-muted-foreground">{row.period}</td>
                        <td className="px-3 py-2.5 text-right tnum">
                          {money(row.monthlyBudget)}
                        </td>
                        <td className="px-3 py-2.5 text-right tnum">{money(row.used)}</td>
                        <td className="px-3 py-2.5 text-right tnum">{money(remaining)}</td>
                        <td className="px-4 py-2.5">
                          <div className="flex items-center gap-2">
                            <BudgetUtilBar used={row.used} total={row.monthlyBudget} />
                            <span className="tnum text-xs text-muted-foreground w-9 text-right">
                              {pct}%
                            </span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )}
        <p className="text-xs text-muted-foreground mt-2">
          Budgets come from Employee Master. Claims are checked against category caps at validation
          (VR-TE02 / VR-TE06).
        </p>
      </PageTabPanel>

      <PageTabPanel value="categories" active={tab} className="mt-4">
        {categories.length === 0 ? (
          <EmptyState
            title="No team expense rules"
            hint="Configure team expense rules on the Rule Book → Team Expenses tab."
          />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {categories.map((cat) => (
              <Card key={cat.category} className="p-4 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-medium">{cat.category}</span>
                  <span className="text-xs text-muted-foreground">{cat.glAccount}</span>
                </div>
                <div className="text-xs text-muted-foreground space-y-1">
                  <div>
                    Receipt required over{" "}
                    <span className="tnum text-foreground">
                      {fmtAud(cat.requiresReceiptOver)}
                    </span>
                  </div>
                  <div>
                    Auto-approve under{" "}
                    <span className="tnum text-foreground">
                      {cat.autoApproveUnder > 0 ? fmtAud(cat.autoApproveUnder) : "—"}
                    </span>
                  </div>
                  <div className="pt-1 italic">{cat.policyNote}</div>
                </div>
              </Card>
            ))}
          </div>
        )}
      </PageTabPanel>

      <InvoiceDetailDrawer
        invoiceId={drawerInvoiceId}
        open={drawerInvoiceId != null}
        onClose={() => setDrawerInvoiceId(null)}
        onUpdated={() => void refetch()}
      />
    </div>
  );
}
