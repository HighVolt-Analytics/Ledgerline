import { useState, type ReactNode } from "react";
import { ArrowRight, ChevronDown, ChevronRight, Plus, Trash2, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/context/ToastContext";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { mergeCoaOptionsWithSavedValue } from "@/lib/coaAccountOptions";
import { defaultSalesRulePostTo } from "@/lib/documentTypeGlDefaults";
import { nextRulePriority } from "@/lib/rulePriority";
import type { SalesRule } from "@/lib/v4RuleBookTypes";
import { AccountBadge } from "./AccountBadge";
import { FieldLabel } from "./FieldLabel";
import {
  reconcileSubLedgerOnLedgerChange,
  SubLedgerField,
} from "./SubLedgerField";

function MatchChip({ children }: { children: ReactNode }) {
  return (
    <Badge variant="outline" className="text-[10px] font-normal font-mono">
      {children}
    </Badge>
  );
}

export function SalesRulesTab({
  rules,
  onChange,
}: {
  rules: SalesRule[];
  onChange: (rules: SalesRule[]) => void;
}) {
  const { toast } = useToast();
  const {
    allAccounts,
    options: revenueOptions,
    hasRealAccounts: hasRevenueAccounts,
    isLoading: coaLoading,
  } = useCoaAccountOptions({ includeEmpty: false });
  const { options: taxOptions } = useCoaAccountOptions({
    includeEmpty: true,
    emptyLabel: "GST Collected (default)",
  });
  const { options: receivableOptions } = useCoaAccountOptions({
    includeEmpty: true,
    emptyLabel: "Accounts Receivable (default)",
  });
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const update = (id: string, patch: Partial<SalesRule>) =>
    onChange(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const updateMatch = (id: string, patch: Partial<SalesRule["matchOn"]>) =>
    onChange(
      rules.map((r) => (r.id === id ? { ...r, matchOn: { ...r.matchOn, ...patch } } : r))
    );

  const updatePost = (id: string, patch: Partial<SalesRule["postTo"]>) =>
    onChange(rules.map((r) => (r.id === id ? { ...r, postTo: { ...r.postTo, ...patch } } : r)));

  const removeRule = (id: string) => {
    onChange(rules.filter((r) => r.id !== id));
    if (expandedId === id) setExpandedId(null);
    toast({ title: "Rule removed" });
  };

  const addRule = () => {
    const id = `sr-${Date.now()}`;
    const defaults = defaultSalesRulePostTo(allAccounts);
    onChange([
      ...rules,
      {
        id,
        name: "New sales rule",
        enabled: true,
        priority: nextRulePriority(rules),
        matchOn: { customerContains: "" },
        postTo: defaults,
        matchedCount: 0,
      },
    ]);
    setExpandedId(id);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground max-w-2xl">
          GL coding for documents routed to Sales Management — customer invoices and receivables.
          Matching rules also route unmatched documents to the sales workspace.
        </p>
        <Button size="sm" onClick={addRule} data-testid="button-new-sales-rule">
          <Plus className="h-4 w-4 mr-1" /> New Rule
        </Button>
      </div>

      <div className="space-y-3">
        {rules.map((rule) => {
          const open = expandedId === rule.id;
          const m = rule.matchOn;
          return (
            <Card key={rule.id} className="overflow-hidden" data-testid={`sales-rule-${rule.id}`}>
              <div className="flex items-start gap-3 p-3">
                <button
                  type="button"
                  className="flex-1 min-w-0 text-left"
                  onClick={() => setExpandedId(open ? null : rule.id)}
                  data-testid={`toggle-sales-${rule.id}`}
                >
                  <div className="flex items-center gap-2 flex-wrap mb-1.5">
                    {open ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                    <TrendingUp className="h-4 w-4 text-primary shrink-0" />
                    <span className="text-sm font-semibold">{rule.name}</span>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap pl-6">
                    {m.docNumberContains && (
                      <MatchChip>doc# ~ {m.docNumberContains}</MatchChip>
                    )}
                    {m.referenceContains && (
                      <MatchChip>ref ~ {m.referenceContains}</MatchChip>
                    )}
                    {m.descriptionContains && (
                      <Badge variant="outline" className="text-[10px] font-normal">
                        desc ~ {m.descriptionContains}
                      </Badge>
                    )}
                    {m.customerContains && (
                      <Badge variant="outline" className="text-[10px] font-normal">
                        customer ~ {m.customerContains}
                      </Badge>
                    )}
                    <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                    <AccountBadge account={rule.postTo.ledger} />
                    {rule.postTo.subLedger && (
                      <span className="text-xs text-muted-foreground">/ {rule.postTo.subLedger}</span>
                    )}
                  </div>
                </button>
                <div className="flex items-center gap-2 shrink-0">
                  <Badge variant="outline" className="text-[10px] font-normal tnum">
                    {rule.matchedCount} matched
                  </Badge>
                  <Switch
                    checked={rule.enabled}
                    onCheckedChange={(v) => update(rule.id, { enabled: v })}
                    className="scale-90"
                    data-testid={`enable-sales-${rule.id}`}
                  />
                </div>
              </div>

              {open && (
                <div className="border-t border-border bg-muted/20 p-3 space-y-4">
                  <FieldLabel label="Rule name">
                    <Input
                      value={rule.name}
                      onChange={(e) => update(rule.id, { name: e.target.value })}
                      className="h-8 text-sm max-w-md"
                    />
                  </FieldLabel>

                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      Match on
                    </h4>
                    <div className="grid sm:grid-cols-2 gap-2.5">
                      <FieldLabel label="Document number contains">
                        <Input
                          value={m.docNumberContains ?? ""}
                          onChange={(e) =>
                            updateMatch(rule.id, { docNumberContains: e.target.value })
                          }
                          className="h-8 text-xs font-mono"
                        />
                      </FieldLabel>
                      <FieldLabel label="Reference contains">
                        <Input
                          value={m.referenceContains ?? ""}
                          onChange={(e) =>
                            updateMatch(rule.id, { referenceContains: e.target.value })
                          }
                          className="h-8 text-xs"
                        />
                      </FieldLabel>
                      <FieldLabel label="Description contains">
                        <Input
                          value={m.descriptionContains ?? ""}
                          onChange={(e) =>
                            updateMatch(rule.id, { descriptionContains: e.target.value })
                          }
                          className="h-8 text-xs"
                        />
                      </FieldLabel>
                      <FieldLabel label="Customer contains">
                        <Input
                          value={m.customerContains ?? ""}
                          onChange={(e) =>
                            updateMatch(rule.id, { customerContains: e.target.value })
                          }
                          className="h-8 text-xs"
                        />
                      </FieldLabel>
                    </div>
                  </div>

                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      Post to
                    </h4>
                    <div className="grid sm:grid-cols-2 gap-2.5 max-w-lg">
                      <FieldLabel label="Revenue ledger (GL)">
                        <Select
                          value={rule.postTo.ledger}
                          onValueChange={(ledger) =>
                            updatePost(rule.id, {
                              ledger,
                              subLedger: reconcileSubLedgerOnLedgerChange(
                                ledger,
                                rule.postTo.subLedger,
                                allAccounts
                              ),
                            })
                          }
                          options={mergeCoaOptionsWithSavedValue(revenueOptions, rule.postTo.ledger)}
                          disabled={coaLoading}
                          className="w-full"
                        />
                      </FieldLabel>
                      <FieldLabel label="Sub-ledger">
                        <SubLedgerField
                          ledger={rule.postTo.ledger}
                          value={rule.postTo.subLedger}
                          onChange={(subLedger) => updatePost(rule.id, { subLedger })}
                          accounts={allAccounts}
                          size="sm"
                        />
                      </FieldLabel>
                      <FieldLabel label="Tax account">
                        <Select
                          value={rule.postTo.taxAccount ?? ""}
                          onValueChange={(taxAccount) => updatePost(rule.id, { taxAccount })}
                          options={mergeCoaOptionsWithSavedValue(
                            taxOptions,
                            rule.postTo.taxAccount ?? ""
                          )}
                          disabled={coaLoading}
                          className="w-full"
                        />
                      </FieldLabel>
                      <FieldLabel label="Receivable account">
                        <Select
                          value={rule.postTo.receivableAccount ?? ""}
                          onValueChange={(receivableAccount) =>
                            updatePost(rule.id, { receivableAccount })
                          }
                          options={mergeCoaOptionsWithSavedValue(
                            receivableOptions,
                            rule.postTo.receivableAccount ?? ""
                          )}
                          disabled={coaLoading}
                          className="w-full"
                        />
                      </FieldLabel>
                    </div>
                    {!coaLoading && !hasRevenueAccounts ? (
                      <p className="text-[10px] text-muted-foreground mt-2">
                        Add accounts in Settings → Chart of accounts.
                      </p>
                    ) : null}
                  </div>

                  <div className="flex justify-end">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-8 px-2 text-xs text-muted-foreground hover:text-destructive"
                      onClick={(e) => {
                        e.stopPropagation();
                        removeRule(rule.id);
                      }}
                      data-testid={`delete-sales-${rule.id}`}
                    >
                      <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          );
        })}
        {rules.length === 0 && (
          <Card className="p-6 text-center text-sm text-muted-foreground">
            No sales rules yet.
          </Card>
        )}
      </div>
    </div>
  );
}
