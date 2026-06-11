import { Activity, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { useRuleBookEvaluation } from "@/hooks/useRuleBookEvaluation";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";
import { AccountBadge } from "./AccountBadge";
import { ConfidenceBar } from "./ConfidenceBar";

export function LiveEvaluation({ ruleBook }: { ruleBook: RuleBookConfigState }) {
  const { result, isLoading, error } = useRuleBookEvaluation(ruleBook);
  const rows = result?.rows ?? [];

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
            {result.source === "invoices" ? "Inbox data" : "Sample data"}
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
          No documents to evaluate. Load documents from the Inbox to see live rule evaluation.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground border-b border-border">
                <th className="px-3 py-2 text-left font-medium">Document</th>
                <th className="px-3 py-2 text-left font-medium">Email Capture rule</th>
                <th className="px-3 py-2 text-left font-medium">Vendor match</th>
                <th className="px-3 py-2 text-left font-medium">Category rule</th>
                <th className="px-3 py-2 text-left font-medium">Ledger</th>
                <th className="px-3 py-2 text-left font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.document.id}
                  className="row-band border-b border-border/60 align-top"
                  data-testid={`eval-row-${row.document.id}`}
                >
                  <td className="px-3 py-2.5">
                    <div className="font-medium tnum">
                      {row.document.invoice_no || row.document.doc_number}
                    </div>
                    <div className="text-xs text-muted-foreground truncate max-w-[180px]">
                      {row.document.vendor}
                    </div>
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
                    {row.vendor_match ? (
                      <div className="min-w-[140px]">
                        <div className="text-xs font-medium truncate max-w-[150px]">
                          {row.vendor_match.vendor_name}
                        </div>
                        <ConfidenceBar value={row.vendor_match.confidence} />
                      </div>
                    ) : (
                      <span className="text-xs text-muted-foreground">Unmatched</span>
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
                      <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap">
                        <span className="h-2 w-2 rounded-full bg-[hsl(var(--chart-1))] shrink-0" />
                        Auto-coded
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-xs whitespace-nowrap">
                        <span className="h-2 w-2 rounded-full bg-[hsl(43_74%_49%)] shrink-0" />
                        Needs review
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
