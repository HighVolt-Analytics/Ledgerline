import { useEffect, useMemo, useState } from "react";
import { EmptyState } from "@/components/EmptyState";
import { ListDetailSkeleton } from "@/components/skeleton/PageSkeletons";
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
import { useInstitutionSettings } from "@/hooks/useInstitutionSettings";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";
import { cn } from "@/lib/cn";
import { matchesListSearch } from "@/lib/listSearch";
import { formatMoneyByCurrencyMap, money } from "@/lib/format";
import {
  employeeBudgetRows,
  invoiceToTeamClaim,
  teamRulesToCategories,
} from "@/lib/routePageAdapters";
import {
  TEAM_EXPENSE_KINDS,
  TEAM_EXPENSE_KIND_LABELS,
  type TeamExpenseKind,
} from "@/lib/v4RuleBookTypes";

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
  const { data: institution } = useInstitutionSettings();
  const institutionCurrency = (institution?.currency || "SGD").trim().toUpperCase() || "SGD";
  const actions = useExpenseClaimActions(ROUTE_TARGET);

  const claims = useMemo(
    () => routed.map((inv) => invoiceToTeamClaim(inv, employees)),
    [routed, employees]
  );
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
  const [kindFilter, setKindFilter] = useState<TeamExpenseKind>("expense_claim");
  const kindCounts = useMemo(() => {
    const counts = Object.fromEntries(
      TEAM_EXPENSE_KINDS.map((kind) => [kind, 0])
    ) as Record<TeamExpenseKind, number>;
    for (const claim of claims) counts[claim.kind] += 1;
    return counts;
  }, [claims]);
  const settlementLedger = ruleBook?.teamExpensePosting?.settlementAccount ?? "";
  const advanceLedgerFor = (submitter: string) => {
    const employee = employees.find((emp) => emp.name === submitter);
    return (
      employee?.advanceSubLedger ||
      employee?.advanceParentLedger ||
      ruleBook?.teamExpensePosting?.defaultAdvanceParentLedger ||
      ""
    );
  };

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
    const teamBudgets = budgets.filter((b) => b.period === "Monthly" && b.category === "All categories");
    const totalBudget = teamBudgets.reduce((s, b) => s + b.monthlyBudget, 0);
    const totalUsed = teamBudgets.reduce((s, b) => s + b.used, 0);
    const util = totalBudget > 0 ? Math.round((totalUsed / totalBudget) * 100) : 0;
    return {
      open,
      postedCount: postedInvoices.length,
      postedByCurrency,
      pending,
      util,
    };
  }, [claims, budgets, routed, institutionCurrency]);

  const kindClaims = useMemo(
    () => claims.filter((claim) => claim.kind === kindFilter),
    [claims, kindFilter]
  );
  const selected = kindClaims.find((e) => e.id === selectedId) ?? kindClaims[0] ?? null;
  const filteredClaims = useMemo(
    () =>
      kindClaims.filter((claim) =>
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
    [kindClaims, searchQuery]
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

      <div
        className="mb-4 inline-flex flex-wrap gap-1 rounded-lg border border-border bg-card p-1"
        role="tablist"
        aria-label="Claim kind"
        data-testid="team-expense-kind-toggle"
      >
        {TEAM_EXPENSE_KINDS.map((kind) => (
          <button
            key={kind}
            type="button"
            role="tab"
            aria-selected={kindFilter === kind}
            onClick={() => {
              setKindFilter(kind);
              setSelectedId(null);
            }}
            data-testid={`kind-toggle-${kind}`}
            className={cn(
              "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              kindFilter === kind
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover-elevate"
            )}
          >
            {TEAM_EXPENSE_KIND_LABELS[kind]}
            <span className="ml-1.5 tnum opacity-70">{kindCounts[kind]}</span>
          </button>
        ))}
      </div>

      <TeamExpenseChannelsStrip />

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-5">
        <KpiCard
          label="Open Claims"
          value={isLoading ? "…" : kpis.open}
          testid="kpi-exp-open"
        />
        <KpiCard
          label="Posted This Month"
          value={isLoading ? "…" : formatMoneyByCurrencyMap(kpis.postedByCurrency)}
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
          <ListDetailSkeleton />
        ) : kindClaims.length === 0 ? (
          <EmptyState
            title={`No ${TEAM_EXPENSE_KIND_LABELS[kindFilter].toLowerCase()} documents yet`}
            hint="Claims arrive via Email, WhatsApp, or Viber when the sender matches an employee in the registry. Switch the kind above or change a claim's kind in its detail panel."
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
                      {(() => {
                        const identity = [claim.employeeId, claim.division, claim.location]
                          .map((part) => (part || "").trim())
                          .filter(Boolean);
                        return identity.length > 0 ? (
                          <div className="text-[10px] text-muted-foreground truncate mt-0.5">
                            {identity.join(" · ")}
                          </div>
                        ) : null;
                      })()}
                      <div className="text-xs text-muted-foreground truncate mt-0.5">
                        {claim.category} · {claim.merchant}
                      </div>
                      {claim.documentRef ? (
                        <div className="text-[10px] text-muted-foreground tnum mt-0.5 truncate">
                          {claim.documentRef}
                        </div>
                      ) : null}
                      {typeof claim.advanceBalance === "number" ? (
                        <div className="text-[10px] text-muted-foreground tnum mt-0.5">
                          Advance left {money(
                            claim.advanceBalance,
                            invoiceById.get(Number(claim.id))?.currency || institutionCurrency
                          )}
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
                    key={selected.id}
                    claim={selected}
                    invoiceId={selectedInvoice.id}
                    invoiceStatus={selectedInvoice.status}
                    hasStoredFile={selectedInvoice.has_stored_file}
                    budget={budget}
                    busy={actions.busyId === selectedInvoice.id}
                    canApprove={actions.canApproveClaim(selectedInvoice.status)}
                    canReject={actions.canRejectClaim(selectedInvoice.status)}
                    canRequestInfo={actions.canRequestInfo(selectedInvoice.status)}
                    advanceLedger={advanceLedgerFor(selected.submitter)}
                    settlementLedger={settlementLedger}
                    advanceBalance={selected.advanceBalance ?? 0}
                    currency={
                      (selectedInvoice.currency || institutionCurrency).trim().toUpperCase() ||
                      institutionCurrency
                    }
                    onChangeKind={async (kind) => {
                      await actions.setKind(selectedInvoice, kind);
                    }}
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
            hint="Add employees with budget caps on the Creations → Employees tab."
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
                          {money(row.monthlyBudget, institutionCurrency)}
                        </td>
                        <td className="px-3 py-2.5 text-right tnum">
                          {money(row.used, institutionCurrency)}
                        </td>
                        <td className="px-3 py-2.5 text-right tnum">
                          {money(remaining, institutionCurrency)}
                        </td>
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
                      {money(cat.requiresReceiptOver, institutionCurrency)}
                    </span>
                  </div>
                  <div>
                    Auto-approve under{" "}
                    <span className="tnum text-foreground">
                      {cat.autoApproveUnder > 0
                        ? money(cat.autoApproveUnder, institutionCurrency)
                        : "—"}
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
