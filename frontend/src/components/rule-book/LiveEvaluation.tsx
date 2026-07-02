import { Activity, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useRuleBookEvaluation } from "@/hooks/useRuleBookEvaluation";
import type { RuleBookEvaluationRow } from "@/api/types";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";
import {
  ROUTE_EXPENSES,
  ROUTE_PURCHASE,
  ROUTE_SALES,
  ROUTE_TEAM,
  counterpartyMatchColumnLabel,
  counterpartyName,
} from "@/lib/invoice";
import { AccountBadge } from "./AccountBadge";
import { ConfidenceBar } from "./ConfidenceBar";

function evalDocumentLabel(row: RuleBookEvaluationRow): string {
  return row.document.doc_number;
}

function evalRowRouteTarget(row: RuleBookEvaluationRow): string | null {
  const route = row.document.route_target?.trim();
  if (route) return route;
  const kind = row.category_rule?.kind ?? row.category_rule_disabled?.kind;
  if (kind === "Sales") return ROUTE_SALES;
  if (kind === "Purchase") return ROUTE_PURCHASE;
  if (kind === "Expense") return ROUTE_EXPENSES;
  if (kind === "Team") return ROUTE_TEAM;
  return null;
}

function evalCounterpartyPendingLabel(row: RuleBookEvaluationRow): string {
  const route = evalRowRouteTarget(row);
  if (route === ROUTE_SALES) return "Pending customer";
  if (route === ROUTE_TEAM) return "Pending employee";
  if (route === ROUTE_PURCHASE || route === ROUTE_EXPENSES) return "Pending vendor";
  return "Pending master";
}

function evalMasterMatch(row: RuleBookEvaluationRow) {
  if (row.counterparty_match) return row.counterparty_match;
  if (row.vendor_match) {
    return {
      kind: "vendor" as const,
      master_id: row.vendor_match.vendor_id,
      master_name: row.vendor_match.vendor_name,
      confidence: row.vendor_match.confidence,
    };
  }
  return null;
}

function evalCounterpartyDisplayName(row: RuleBookEvaluationRow): string {
  return counterpartyName({
    vendor: row.document.vendor,
    route_target: evalRowRouteTarget(row),
    extracted_fields: null,
  });
}

export function LiveEvaluation({ ruleBook }: { ruleBook: RuleBookConfigState }) {
  const { result, isLoading, error } = useRuleBookEvaluation(ruleBook);
  const rows = result?.rows ?? [];

  const routeTargets = rows.map(evalRowRouteTarget).filter(Boolean) as string[];
  const uniqueRoutes = new Set(routeTargets);
  const mixedCounterparty = uniqueRoutes.size > 1;
  const primaryRoute = uniqueRoutes.size === 1 ? routeTargets[0] : null;
  const masterMatchColumn = counterpartyMatchColumnLabel({
    routeTarget: primaryRoute,
    mixed: mixedCounterparty,
  });

  const sourceHint =
    result?.source === "invoices"
      ? "Evaluated against invoices in your organisation."
      : result?.source === "sample"
        ? "No invoices yet — showing sample documents."
        : "Evaluating documents against your rule books…";

  return (
    <Card className="p-4 mt-6" data-testid="live-eval">
      <div className="flex items-center justify-between gap-3 mb-1">
        <div className="flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold">Live evaluation</h3>
          {isLoading && <Loader2 className="h-3.5 w-3.5 animate-spin text-muted-foreground" />}
        </div>
        {result && (
          <span className="text-[10px] text-muted-foreground uppercase tracking-wide">
            {result.source === "invoices" ? "Upload data" : "Sample data"}
          </span>
        )}
      </div>
      <p className="text-xs text-muted-foreground mb-3">{sourceHint}</p>

      {error && (
        <p className="text-sm text-destructive py-3" data-testid="live-eval-error">
          {error}
        </p>
      )}

      {!error && rows.length === 0 && !isLoading ? (
        <p className="text-sm text-muted-foreground py-6 text-center">
          No documents to evaluate. Load documents from Upload to see live rule evaluation.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b border-border">
                <th className="px-3 py-2 text-left font-medium">Document</th>
                <th className="px-3 py-2 text-left font-medium">Doc type</th>
                <th className="px-3 py-2 text-left font-medium">Capture rule</th>
                <th className="px-3 py-2 text-left font-medium">{masterMatchColumn}</th>
                <th className="px-3 py-2 text-left font-medium">Category rule</th>
                <th className="px-3 py-2 text-left font-medium">Ledger</th>
                <th className="px-3 py-2 text-left font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const masterMatch = evalMasterMatch(row);
                return (
                  <tr
                    key={row.document.id}
                    className="row-band border-b border-border/60 align-top"
                    data-testid={`eval-row-${row.document.id}`}
                  >
                    <td className="px-3 py-2.5">
                      <div className="font-medium tnum">{evalDocumentLabel(row)}</div>
                      {row.document.invoice_no ? (
                        <div className="text-[11px] text-muted-foreground tnum truncate max-w-[180px]">
                          {row.document.invoice_no}
                        </div>
                      ) : null}
                      <div className="text-xs text-muted-foreground truncate max-w-[180px]">
                        {evalCounterpartyDisplayName(row)}
                      </div>
                    </td>
                    <td className="px-3 py-2.5">
                      {row.document.document_type_code ? (
                        <Badge variant="outline" className="text-[11px] font-medium tnum">
                          {row.document.document_type_code}
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      {row.email_rule ? (
                        <Badge variant="outline" className="text-[11px] font-normal">
                          {row.email_rule.name}
                        </Badge>
                      ) : row.email_rule_disabled ? (
                        <Badge
                          variant="outline"
                          className="text-[11px] font-normal border-dashed text-[hsl(43_74%_49%)]"
                        >
                          Would match: {row.email_rule_disabled.name}
                        </Badge>
                      ) : (
                        <span className="text-xs text-muted-foreground">No rule</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      {masterMatch ? (
                        <div className="min-w-[140px]">
                          <div className="text-xs font-medium truncate max-w-[150px]">
                            {masterMatch.master_name}
                          </div>
                          <ConfidenceBar value={masterMatch.confidence} />
                        </div>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]">
                          <span className="h-2 w-2 rounded-full bg-[hsl(43_74%_49%)] shrink-0" />
                          {evalCounterpartyPendingLabel(row)}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      {row.category_rule ? (
                        <div className="flex items-center gap-1.5">
                          <Badge
                            variant="outline"
                            className="text-[10px] font-normal text-muted-foreground"
                          >
                            {row.category_rule.kind}
                          </Badge>
                          <span className="text-xs">{row.category_rule.label}</span>
                        </div>
                      ) : row.category_rule_disabled ? (
                        <div className="flex items-center gap-1.5">
                          <Badge
                            variant="outline"
                            className="text-[10px] font-normal border-dashed text-[hsl(43_74%_49%)]"
                          >
                            {row.category_rule_disabled.kind}
                          </Badge>
                          <span className="text-xs text-[hsl(43_74%_49%)]">
                            Would match: {row.category_rule_disabled.label}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">No rule matched</span>
                      )}
                    </td>
                    <td className="px-3 py-2.5">
                      <AccountBadge account={row.document.primary_account} />
                    </td>
                    <td className="px-3 py-2.5">
                      {row.auto_coded ? (
                        <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap rounded-full border border-[hsl(var(--chart-1)/0.4)] px-2 py-0.5 text-[hsl(var(--chart-1))]">
                          <span className="h-2 w-2 rounded-full bg-[hsl(var(--chart-1))] shrink-0" />
                          Auto coded
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap rounded-full border border-[hsl(43_74%_49%/0.5)] px-2 py-0.5 text-[hsl(36_80%_38%)] dark:text-[hsl(43_74%_62%)]">
                          <span className="h-2 w-2 rounded-full bg-[hsl(43_74%_49%)] shrink-0" />
                          Needs review
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
