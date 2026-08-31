import { useState, type ReactNode } from "react";
import { ArrowRight, ChevronDown, ChevronRight, Landmark, Plus, Trash2 } from "lucide-react";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/context/ToastContext";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { defaultExpensePostingLedger, mergeCoaOptionsWithSavedValue } from "@/lib/coaAccountOptions";
import { nextRulePriority } from "@/lib/rulePriority";
import type { BankNarrationRule } from "@/lib/v4RuleBookTypes";
import { AccountBadge } from "./AccountBadge";
import { FieldLabel } from "./FieldLabel";
import {
  reconcileSubLedgerOnLedgerChange,
  SubLedgerField,
} from "./SubLedgerField";
import { RuleBookEmptyPanel } from "./RuleBookEmptyPanel";

function MatchChip({ children }: { children: ReactNode }) {
  return (
    <Badge variant="outline" className="text-[10px] font-normal">
      {children}
    </Badge>
  );
}

export function BankNarrationRulesTab({
  rules,
  onChange,
  canEdit = true,
}: {
  rules: BankNarrationRule[];
  onChange: (rules: BankNarrationRule[]) => void;
  canEdit?: boolean;
}) {
  const { toast } = useToast();
  const {
    allAccounts,
    options: ledgerOptions,
    hasRealAccounts,
    isLoading: coaLoading,
  } = useCoaAccountOptions({ includeEmpty: false });
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null);

  const update = (id: string, patch: Partial<BankNarrationRule>) =>
    onChange(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const updateMatch = (id: string, patch: Partial<BankNarrationRule["matchOn"]>) =>
    onChange(
      rules.map((r) => (r.id === id ? { ...r, matchOn: { ...r.matchOn, ...patch } } : r))
    );

  const updatePost = (id: string, patch: Partial<BankNarrationRule["postTo"]>) =>
    onChange(rules.map((r) => (r.id === id ? { ...r, postTo: { ...r.postTo, ...patch } } : r)));

  const removeRule = (id: string) => {
    onChange(rules.filter((r) => r.id !== id));
    if (expandedId === id) setExpandedId(null);
    setPendingDeleteId(null);
    toast({ title: "Rule removed" });
  };

  const addRule = () => {
    const id = `bnr-${Date.now()}`;
    onChange([
      ...rules,
      {
        id,
        name: "New bank narration rule",
        enabled: true,
        priority: nextRulePriority(rules),
        matchOn: { descriptionContains: "" },
        postTo: { ledger: defaultExpensePostingLedger(allAccounts), subLedger: "" },
        matchedCount: 0,
      },
    ]);
    setExpandedId(id);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground max-w-2xl">
          Assign a GL category to unmatched bank lines when the statement text matches. Matched
          payments and collections keep their own category — these rules never apply to them.
        </p>
        <Button
          size="sm"
          onClick={addRule}
          disabled={!canEdit}
          data-testid="button-new-bank-narration-rule"
        >
          <Plus className="h-4 w-4 mr-1" /> New Rule
        </Button>
      </div>

      <div className="space-y-3">
        {rules.map((rule) => {
          const open = expandedId === rule.id;
          const m = rule.matchOn;
          return (
            <Card
              key={rule.id}
              className="overflow-hidden"
              data-testid={`bank-narration-rule-${rule.id}`}
            >
              <div className="flex items-start gap-3 p-3">
                <button
                  type="button"
                  className="flex-1 min-w-0 text-left"
                  onClick={() => setExpandedId(open ? null : rule.id)}
                  data-testid={`toggle-bank-narration-${rule.id}`}
                >
                  <div className="flex items-center gap-2 flex-wrap mb-1.5">
                    {open ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                    <Landmark className="h-4 w-4 text-primary shrink-0" />
                    <span className="text-sm font-semibold">{rule.name}</span>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap pl-6">
                    {m.descriptionContains ? (
                      <MatchChip>text contains “{m.descriptionContains}”</MatchChip>
                    ) : null}
                    {m.descriptionPattern ? (
                      <MatchChip>pattern {m.descriptionPattern}</MatchChip>
                    ) : null}
                    <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                    <AccountBadge account={rule.postTo.ledger} />
                    {rule.postTo.subLedger ? (
                      <span className="text-xs text-muted-foreground">
                        / {rule.postTo.subLedger}
                      </span>
                    ) : null}
                  </div>
                </button>
                <div className="flex items-center gap-2 shrink-0">
                  <Badge variant="outline" className="text-[10px] font-normal tnum">
                    {rule.matchedCount} matched
                  </Badge>
                  <Switch
                    checked={rule.enabled}
                    onCheckedChange={(v) => update(rule.id, { enabled: v })}
                    disabled={!canEdit}
                    className="scale-90"
                    data-testid={`enable-bank-narration-${rule.id}`}
                  />
                </div>
              </div>

              {open && (
                <div className="border-t border-border bg-muted/20 p-3 space-y-4">
                  <FieldLabel label="Rule name">
                    <Input
                      value={rule.name}
                      onChange={(e) => update(rule.id, { name: e.target.value })}
                      disabled={!canEdit}
                      className="h-8 text-sm max-w-md"
                    />
                  </FieldLabel>

                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      When bank text matches
                    </h4>
                    <div className="grid sm:grid-cols-2 gap-2.5">
                      <FieldLabel label="Description contains">
                        <Input
                          value={m.descriptionContains ?? ""}
                          onChange={(e) =>
                            updateMatch(rule.id, { descriptionContains: e.target.value })
                          }
                          disabled={!canEdit}
                          placeholder="e.g. ATM or NETFLIX"
                          className="h-8 text-xs"
                        />
                      </FieldLabel>
                      <FieldLabel label="Description pattern (regex)">
                        <Input
                          value={m.descriptionPattern ?? ""}
                          onChange={(e) =>
                            updateMatch(rule.id, { descriptionPattern: e.target.value })
                          }
                          disabled={!canEdit}
                          placeholder="optional advanced match"
                          className="h-8 text-xs font-mono"
                        />
                      </FieldLabel>
                    </div>
                    <p className="text-[10px] text-muted-foreground mt-2">
                      Both fields must match when both are filled. Patterns use RE2 (linear-time;
                      no backreferences or lookaround). Invalid patterns are skipped.
                    </p>
                  </div>

                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      Post to
                    </h4>
                    <div className="grid sm:grid-cols-2 gap-2.5 max-w-lg">
                      <FieldLabel label="Ledger (GL)">
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
                          options={mergeCoaOptionsWithSavedValue(
                            ledgerOptions,
                            rule.postTo.ledger
                          )}
                          disabled={!canEdit || coaLoading}
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
                          disabled={!canEdit}
                        />
                      </FieldLabel>
                    </div>
                    {!coaLoading && !hasRealAccounts ? (
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
                      disabled={!canEdit}
                      onClick={(e) => {
                        e.stopPropagation();
                        setPendingDeleteId(rule.id);
                      }}
                      data-testid={`delete-bank-narration-${rule.id}`}
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
          <RuleBookEmptyPanel icon={Landmark} title="No bank narration rules yet." />
        )}
      </div>

      <ConfirmDialog
        open={pendingDeleteId != null}
        title="Delete this bank narration rule?"
        description="Unmatched bank lines will no longer be auto-categorized by this rule. This cannot be undone from here."
        confirmLabel="Delete rule"
        destructive
        onCancel={() => setPendingDeleteId(null)}
        onConfirm={() => {
          if (pendingDeleteId) removeRule(pendingDeleteId);
        }}
        data-testid="confirm-delete-bank-narration-rule"
      />
    </div>
  );
}
