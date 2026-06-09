import { useState, type ReactNode } from "react";
import { ArrowRight, ChevronDown, ChevronRight, Plus, Receipt, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/context/ToastContext";
import type { ExpenseRule } from "@/lib/v4RuleBookTypes";
import { LEDGER_ACCOUNTS } from "@/lib/v4RuleBookTypes";
import { AccountBadge } from "./AccountBadge";
import { FieldLabel } from "./FieldLabel";

function MatchChip({ children }: { children: ReactNode }) {
  return (
    <Badge variant="outline" className="text-[10px] font-normal font-mono">
      {children}
    </Badge>
  );
}

export function ExpensesRulesTab({
  rules,
  onChange,
}: {
  rules: ExpenseRule[];
  onChange: (rules: ExpenseRule[]) => void;
}) {
  const { toast } = useToast();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const update = (id: string, patch: Partial<ExpenseRule>) =>
    onChange(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const updateMatch = (id: string, patch: Partial<ExpenseRule["matchOn"]>) =>
    onChange(
      rules.map((r) => (r.id === id ? { ...r, matchOn: { ...r.matchOn, ...patch } } : r))
    );

  const updatePost = (id: string, patch: Partial<ExpenseRule["postTo"]>) =>
    onChange(rules.map((r) => (r.id === id ? { ...r, postTo: { ...r.postTo, ...patch } } : r)));

  const removeRule = (id: string) => {
    onChange(rules.filter((r) => r.id !== id));
    if (expandedId === id) setExpandedId(null);
    toast({ title: "Rule removed" });
  };

  const addRule = () => {
    const id = `er-${Date.now()}`;
    onChange([
      ...rules,
      {
        id,
        name: "New expense rule",
        enabled: true,
        matchOn: { descriptionContains: "" },
        postTo: { ledger: LEDGER_ACCOUNTS[0], subLedger: "" },
        matchedCount: 0,
      },
    ]);
    setExpandedId(id);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground max-w-2xl">
          Code non-PO business expenses — utility bills, subscriptions, professional services — by
          document number, reference, or description.
        </p>
        <Button size="sm" onClick={addRule} data-testid="button-new-expense-rule">
          <Plus className="h-4 w-4 mr-1" /> New Rule
        </Button>
      </div>

      <div className="space-y-3">
        {rules.map((rule) => {
          const open = expandedId === rule.id;
          const m = rule.matchOn;
          return (
            <Card key={rule.id} className="overflow-hidden" data-testid={`expense-rule-${rule.id}`}>
              <div className="flex items-start gap-3 p-3">
                <button
                  type="button"
                  className="flex-1 min-w-0 text-left"
                  onClick={() => setExpandedId(open ? null : rule.id)}
                  data-testid={`toggle-expense-${rule.id}`}
                >
                  <div className="flex items-center gap-2 flex-wrap mb-1.5">
                    {open ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                    <Receipt className="h-4 w-4 text-primary shrink-0" />
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
                    {m.vendorContains && (
                      <Badge variant="outline" className="text-[10px] font-normal">
                        vendor ~ {m.vendorContains}
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
                    data-testid={`enable-expense-${rule.id}`}
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
                      <FieldLabel label="Vendor contains">
                        <Input
                          value={m.vendorContains ?? ""}
                          onChange={(e) =>
                            updateMatch(rule.id, { vendorContains: e.target.value })
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
                      <FieldLabel label="Ledger (GL)">
                        <Select
                          value={rule.postTo.ledger}
                          onValueChange={(ledger) => updatePost(rule.id, { ledger })}
                          options={toSelectOptions(LEDGER_ACCOUNTS)}
                          className="w-full"
                        />
                      </FieldLabel>
                      <FieldLabel label="Sub-ledger">
                        <Input
                          value={rule.postTo.subLedger}
                          onChange={(e) => updatePost(rule.id, { subLedger: e.target.value })}
                          className="h-8 text-xs"
                        />
                      </FieldLabel>
                    </div>
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
                      data-testid={`delete-expense-${rule.id}`}
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
            No expense rules yet.
          </Card>
        )}
      </div>
    </div>
  );
}
