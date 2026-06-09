import { useMemo, useState } from "react";
import { CheckCircle2, Mail, MessageCircle, Smartphone } from "lucide-react";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { PageHeader } from "@/components/PageHeader";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { BudgetUtilBar } from "@/components/team-expenses/BudgetUtilBar";
import { ClaimDetailPanel } from "@/components/team-expenses/ClaimDetailPanel";
import { ChannelBadge, ExpenseStateBadge } from "@/components/team-expenses/ExpenseBadges";
import { RoutedInvoicesPanel } from "@/components/rule-book/RoutedInvoicesPanel";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useEmployeeMasters } from "@/hooks/useMasterData";
import { useRuleBookConfig } from "@/hooks/useRuleBookConfig";
import { useRoutedInvoices } from "@/hooks/useRoutedInvoices";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import {
  employeeBudgetRows,
  invoiceToTeamClaim,
  teamRulesToCategories,
} from "@/lib/routePageAdapters";
import { CLAIM_CHANNELS, fmtAud, type ExpenseState } from "@/lib/v4MockData";

function initials(name: string) {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .join("")
    .slice(0, 2)
    .toUpperCase();
}

function channelIcon(id: string) {
  if (id === "em") return Mail;
  if (id === "mob") return Smartphone;
  return MessageCircle;
}

export function TeamExpensesPage() {
  const { data: routed = [], isLoading } = useRoutedInvoices("Team Expenses");
  const { data: employees = [] } = useEmployeeMasters();
  const { data: ruleBook } = useRuleBookConfig();

  const claims = useMemo(() => routed.map(invoiceToTeamClaim), [routed]);
  const budgets = useMemo(() => employeeBudgetRows(employees), [employees]);
  const categories = useMemo(
    () => teamRulesToCategories(ruleBook?.teamExpenseRules ?? []),
    [ruleBook?.teamExpenseRules]
  );

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [claimOverrides, setClaimOverrides] = useState<Record<string, ExpenseState>>({});
  const [openChannel, setOpenChannel] = useState<string | null>(null);
  const [tab, setTab] = useState("claims");

  const expenses = useMemo(
    () =>
      claims.map((claim) => ({
        ...claim,
        state: claimOverrides[claim.id] ?? claim.state,
      })),
    [claims, claimOverrides]
  );

  const kpis = useMemo(() => {
    const open = expenses.filter((e) => e.state === "New" || e.state === "In Review").length;
    const approvedRows = expenses.filter(
      (e) => e.state === "Approved" || e.state === "Posted to Ledger"
    );
    const approvedTotal = approvedRows.reduce((s, e) => s + e.amount, 0);
    const pending = expenses.filter((e) => e.state === "In Review").length;
    const teamBudgets = budgets.filter((b) => b.period === "Monthly" && b.category === "All categories");
    const totalBudget = teamBudgets.reduce((s, b) => s + b.monthlyBudget, 0);
    const totalUsed = teamBudgets.reduce((s, b) => s + b.used, 0);
    const util = totalBudget > 0 ? Math.round((totalUsed / totalBudget) * 100) : 0;
    return { open, approvedCount: approvedRows.length, approvedTotal, pending, util };
  }, [expenses, budgets]);

  const selected = expenses.find((e) => e.id === selectedId) ?? expenses[0] ?? null;
  const budget = selected
    ? budgets.find((b) => b.owner !== "Team" && b.category === selected.category)
    : undefined;

  const setExpenseState = (id: string, state: ExpenseState) => {
    setClaimOverrides((prev) => ({ ...prev, [id]: state }));
  };

  return (
    <div>
      <PageHeader
        title="Team Expenses"
        subtitle="Employee claims captured from messaging channels, approved against per-category budgets, posted to the ledger."
      />

      <div className="flex flex-wrap gap-2 mb-5">
        {CLAIM_CHANNELS.map((ch) => {
          const Icon = channelIcon(ch.id);
          return (
            <div key={ch.id} className="relative">
              <button
                type="button"
                onClick={() => setOpenChannel(openChannel === ch.id ? null : ch.id)}
                data-testid={`channel-${ch.id}`}
                className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-xs hover-elevate"
              >
                <Icon className="h-3.5 w-3.5 text-primary" />
                <span className="font-medium">{ch.name}</span>
                <span className="text-muted-foreground hidden md:inline">· {ch.detail}</span>
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full rounded-full bg-[hsl(145_63%_42%)] opacity-60 animate-ping" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-[hsl(145_63%_42%)]" />
                </span>
              </button>
              {openChannel === ch.id && (
                <Card className="absolute z-20 mt-1 p-3 w-56 text-xs space-y-2 shadow-md">
                  <div className="font-medium">{ch.name}</div>
                  <div className="text-muted-foreground">{ch.detail}</div>
                  <div className="flex items-center gap-1 text-[hsl(145_55%_38%)] dark:text-[hsl(145_55%_60%)]">
                    <CheckCircle2 className="h-4 w-4 -ml-1" />
                    Connected · healthy
                  </div>
                  <div className="flex gap-2 pt-1">
                    <Button size="sm" variant="outline" className="h-7 text-xs flex-1">
                      Reconnect
                    </Button>
                    <Button size="sm" variant="outline" className="h-7 text-xs flex-1">
                      Test
                    </Button>
                  </div>
                </Card>
              )}
            </div>
          );
        })}
      </div>

      <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-5">
        <KpiCard
          label="Open Claims"
          value={isLoading ? "…" : kpis.open}
          testid="kpi-exp-open"
        />
        <KpiCard
          label="Approved This Month"
          value={isLoading ? "…" : fmtAud(kpis.approvedTotal)}
          testid="kpi-exp-approved"
          delta={
            !isLoading && kpis.approvedCount > 0
              ? { dir: "up", text: `${kpis.approvedCount} claims`, good: true }
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
        routeTarget="Team Expenses"
        title="Documents routed from Rule Book"
        hint="Employee channel claims routed here by email capture or team expense rules."
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
        ) : expenses.length === 0 ? (
          <EmptyState
            title="No team expense claims yet"
            hint="Documents routed to Team Expenses appear here after email capture or rule-book remap."
          />
        ) : (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
            <div className="space-y-2 lg:max-h-[calc(100dvh-360px)] lg:overflow-y-auto lg:pr-1">
              {expenses.map((claim) => (
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
              {selected ? (
                <Card className="p-4">
                  <ClaimDetailPanel
                    claim={selected}
                    budget={budget}
                    onStateChange={setExpenseState}
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
    </div>
  );
}
