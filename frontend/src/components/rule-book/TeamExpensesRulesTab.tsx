import { useState } from "react";
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Plus,
  Trash2,
  Users,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NumericInput } from "@/components/ui/numeric-input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/context/ToastContext";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { cn } from "@/lib/cn";
import { defaultExpensePostingLedger, mergeCoaOptionsWithSavedValue } from "@/lib/coaAccountOptions";
import { fmtAud } from "@/lib/v4MockData";
import { nextRulePriority } from "@/lib/rulePriority";
import type { TeamExpenseRule } from "@/lib/v4RuleBookTypes";
import { TEAM_CHANNELS } from "@/lib/v4RuleBookTypes";
import { AccountBadge } from "./AccountBadge";
import { FieldLabel } from "./FieldLabel";
import {
  reconcileSubLedgerOnLedgerChange,
  SubLedgerField,
} from "./SubLedgerField";
import { RuleBookEmptyPanel } from "./RuleBookEmptyPanel";

function ChannelBadge({ channel }: { channel: string }) {
  if (channel === "Any") {
    return (
      <Badge variant="outline" className="text-[10px] font-normal">
        Any channel
      </Badge>
    );
  }
  const styles: Record<string, string> = {
    WhatsApp: "border-[hsl(var(--chart-1)/0.4)] text-[hsl(var(--chart-1))]",
    Viber: "border-primary/40 text-primary",
    Mobile: "border-border text-muted-foreground",
    Web: "border-border text-muted-foreground",
  };
  return (
    <Badge
      variant="outline"
      className={cn("text-[10px] font-normal", styles[channel] ?? styles.Web)}
    >
      {channel}
    </Badge>
  );
}

export function TeamExpensesRulesTab({
  rules,
  onChange,
}: {
  rules: TeamExpenseRule[];
  onChange: (rules: TeamExpenseRule[]) => void;
}) {
  const { toast } = useToast();
  const {
    allAccounts,
    options: ledgerOptions,
    hasRealAccounts,
    isLoading: coaLoading,
  } = useCoaAccountOptions({ includeEmpty: false });
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const update = (id: string, patch: Partial<TeamExpenseRule>) =>
    onChange(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const updateMatch = (id: string, patch: Partial<TeamExpenseRule["matchOn"]>) =>
    onChange(
      rules.map((r) => (r.id === id ? { ...r, matchOn: { ...r.matchOn, ...patch } } : r))
    );

  const updatePost = (id: string, patch: Partial<TeamExpenseRule["postTo"]>) =>
    onChange(rules.map((r) => (r.id === id ? { ...r, postTo: { ...r.postTo, ...patch } } : r)));

  const updatePolicy = (id: string, patch: Partial<TeamExpenseRule["policy"]>) =>
    onChange(
      rules.map((r) => (r.id === id ? { ...r, policy: { ...r.policy, ...patch } } : r))
    );

  const removeRule = (id: string) => {
    onChange(rules.filter((r) => r.id !== id));
    if (expandedId === id) setExpandedId(null);
    toast({ title: "Rule removed" });
  };

  const addRule = () => {
    const id = `tr-${Date.now()}`;
    onChange([
      ...rules,
      {
        id,
        name: "New team expense rule",
        enabled: true,
        priority: nextRulePriority(rules),
        matchOn: { channelEquals: "Any" },
        postTo: { ledger: defaultExpensePostingLedger(allAccounts), subLedger: "" },
        policy: { requireReceipt: true, receiptThreshold: 25, autoApproveBelow: 30 },
        matchedCount: 0,
      },
    ]);
    setExpandedId(id);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground max-w-2xl">
          GL coding and policy for documents routed to Team Expenses (employee claims). Channel
          rules here refine ledger and limits — they do not set workspace routing. Credit sides
          come from the claim kind: Rule Book → Posting → Team expense posting sets the settlement
          and advance parent, and each employee posts to their own advance sub-ledger.
        </p>
        <Button size="sm" onClick={addRule} data-testid="button-new-team-rule">
          <Plus className="h-4 w-4 mr-1" /> New Rule
        </Button>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        {rules.map((rule) => {
          const open = expandedId === rule.id;
          const m = rule.matchOn;
          return (
            <Card
              key={rule.id}
              className="overflow-hidden md:col-span-2"
              data-testid={`team-rule-${rule.id}`}
            >
              <div className="flex items-start gap-3 p-3">
                <button
                  type="button"
                  className="flex-1 min-w-0 text-left"
                  onClick={() => setExpandedId(open ? null : rule.id)}
                  data-testid={`toggle-team-${rule.id}`}
                >
                  <div className="flex items-center gap-2 flex-wrap mb-1.5">
                    {open ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                    <Users className="h-4 w-4 text-primary shrink-0" />
                    <span className="text-sm font-semibold">{rule.name}</span>
                    <ChannelBadge channel={m.channelEquals ?? "Any"} />
                  </div>
                  <div className="flex items-center gap-2 flex-wrap pl-6">
                    <AccountBadge account={rule.postTo.ledger} />
                    {rule.postTo.subLedger && (
                      <span className="text-xs text-muted-foreground">/ {rule.postTo.subLedger}</span>
                    )}
                    <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                    {rule.policy.autoApproveBelow > 0 ? (
                      <Badge variant="outline" className="text-[10px] font-normal">
                        auto-approve &lt; {fmtAud(rule.policy.autoApproveBelow)}
                      </Badge>
                    ) : (
                      <Badge
                        variant="outline"
                        className="text-[10px] font-normal border-destructive/40 text-destructive"
                      >
                        no auto-approve
                      </Badge>
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
                    data-testid={`enable-team-${rule.id}`}
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
                    <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
                      <FieldLabel label="Description contains">
                        <Input
                          value={m.descriptionContains ?? ""}
                          onChange={(e) =>
                            updateMatch(rule.id, { descriptionContains: e.target.value })
                          }
                          className="h-8 text-xs"
                        />
                      </FieldLabel>
                      <FieldLabel label="Merchant contains">
                        <Input
                          value={m.merchantContains ?? ""}
                          onChange={(e) =>
                            updateMatch(rule.id, { merchantContains: e.target.value })
                          }
                          className="h-8 text-xs"
                        />
                      </FieldLabel>
                      <FieldLabel label="Channel">
                        <Select
                          value={m.channelEquals ?? "Any"}
                          onValueChange={(channelEquals) =>
                            updateMatch(rule.id, { channelEquals })
                          }
                          options={toSelectOptions(TEAM_CHANNELS)}
                          className="w-full"
                        />
                      </FieldLabel>
                      <FieldLabel label="Amount min ($)">
                        <NumericInput
                          value={m.amountMin}
                          optional
                          hideZero={false}
                          onValueChange={(amountMin) => updateMatch(rule.id, { amountMin })}
                          className="h-8 text-xs"
                        />
                      </FieldLabel>
                      <FieldLabel label="Amount max ($)">
                        <NumericInput
                          value={m.amountMax}
                          optional
                          hideZero={false}
                          onValueChange={(amountMax) => updateMatch(rule.id, { amountMax })}
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
                          options={mergeCoaOptionsWithSavedValue(ledgerOptions, rule.postTo.ledger)}
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
                    </div>
                    {!coaLoading && !hasRealAccounts ? (
                      <p className="text-[10px] text-muted-foreground mt-2">
                        Add accounts in Settings → Chart of accounts.
                      </p>
                    ) : null}
                  </div>

                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      Policy
                    </h4>
                    <div className="grid sm:grid-cols-3 gap-2.5 items-end">
                      <FieldLabel label="Receipt threshold ($)">
                        <NumericInput
                          value={rule.policy.receiptThreshold}
                          onValueChange={(receiptThreshold) =>
                            updatePolicy(rule.id, { receiptThreshold: receiptThreshold ?? 0 })
                          }
                          className="h-8 text-xs"
                        />
                      </FieldLabel>
                      <FieldLabel label="Auto-approve below ($)">
                        <NumericInput
                          value={rule.policy.autoApproveBelow}
                          onValueChange={(autoApproveBelow) =>
                            updatePolicy(rule.id, { autoApproveBelow: autoApproveBelow ?? 0 })
                          }
                          className="h-8 text-xs"
                        />
                      </FieldLabel>
                      <label className="inline-flex items-center gap-2 text-xs pb-1.5">
                        <Switch
                          checked={rule.policy.requireReceipt}
                          onCheckedChange={(v) => updatePolicy(rule.id, { requireReceipt: v })}
                          className="scale-90"
                        />
                        Require receipt
                      </label>
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
                      data-testid={`delete-team-${rule.id}`}
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
          <RuleBookEmptyPanel
            className="md:col-span-2"
            icon={Users}
            title="No team expense rules yet."
          />
        )}
      </div>
    </div>
  );
}
