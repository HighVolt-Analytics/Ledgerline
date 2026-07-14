import { useState } from "react";
import {
  Activity,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Inbox,
  Plus,
  Trash2,
} from "lucide-react";
import {
  moveRuleInPriorityOrder,
  nextSerialPriority,
  sortByPriority,
  withSerialPriorities,
} from "@/lib/rulePriority";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { RuleBookEmptyPanel } from "./RuleBookEmptyPanel";
import { Switch } from "@/components/ui/switch";
import { DEFAULT_MAILBOX } from "@/lib/v4RuleBookMockData";
import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";
import { INGEST_ACTION_ROUTE_PLACEHOLDER } from "@/lib/v4RuleBookTypes";
import { ConditionBuilder } from "@/components/rule-book/ConditionBuilder";

export function IngestionTab({
  rules,
  onChange,
}: {
  rules: EmailCaptureRule[];
  onChange: (rules: EmailCaptureRule[]) => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const updateRule = (id: string, patch: Partial<EmailCaptureRule>) => {
    onChange(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  const addRule = () => {
    const id = `ec-${Date.now()}`;
    const next: EmailCaptureRule = {
      id,
      name: "New ingestion rule",
      enabled: true,
      priority: nextSerialPriority(rules),
      mailbox: DEFAULT_MAILBOX,
      root: {
        type: "group",
        operator: "AND",
        children: [{ type: "condition", field: "subject", operator: "contains", value: "" }],
      },
      action: {
        saveAttachment: true,
        routeTo: INGEST_ACTION_ROUTE_PLACEHOLDER,
        tags: [],
      },
      matchedCount: 0,
      lastMatched: "—",
    };
    onChange(withSerialPriorities([...rules, next]));
    setExpandedId(id);
  };

  const removeRule = (id: string) =>
    onChange(withSerialPriorities(rules.filter((r) => r.id !== id)));

  const moveRule = (id: string, direction: -1 | 1) => {
    onChange(moveRuleInPriorityOrder(rules, id, direction));
  };

  const sorted = sortByPriority(rules);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground max-w-2xl">
          Gate which email attachments enter the document pipeline. Rules are checked in S.No
          order — first match wins. Matching rules accept attachments for OCR only — they do not
          route to Purchase, Expenses, or Team workspaces. Upload and WhatsApp use separate channel
          gates.
        </p>
        <Button size="sm" onClick={addRule} data-testid="button-new-email-rule">
          <Plus className="h-4 w-4 mr-1" /> New Rule
        </Button>
      </div>

      <div className="space-y-3">
        {sorted.map((rule, index) => {
          const open = expandedId === rule.id;
          const serial = index + 1;
          return (
            <Card key={rule.id} className="overflow-hidden" data-testid={`email-rule-${rule.id}`}>
              <div className="flex items-start gap-3 p-3">
                <div className="flex items-center gap-1 pt-0.5">
                  <div className="flex flex-col">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-5 w-5 p-0 text-muted-foreground"
                      disabled={index === 0}
                      onClick={() => moveRule(rule.id, -1)}
                      aria-label={`Move rule ${serial} up`}
                      data-testid={`move-up-email-${rule.id}`}
                    >
                      <ChevronUp className="h-3.5 w-3.5" />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-5 w-5 p-0 text-muted-foreground"
                      disabled={index === sorted.length - 1}
                      onClick={() => moveRule(rule.id, 1)}
                      aria-label={`Move rule ${serial} down`}
                      data-testid={`move-down-email-${rule.id}`}
                    >
                      <ChevronDown className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                  <span
                    className="inline-flex h-6 min-w-6 items-center justify-center rounded-md bg-muted px-1 text-xs font-semibold tnum"
                    title="S.No — check order (first match wins)"
                    aria-label={`S.No ${serial}`}
                  >
                    {serial}
                  </span>
                </div>
                <button
                  type="button"
                  className="flex-1 min-w-0 text-left"
                  onClick={() => setExpandedId(open ? null : rule.id)}
                  data-testid={`toggle-email-rule-${rule.id}`}
                >
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    {open ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                    <Inbox className="h-4 w-4 text-primary shrink-0" />
                    <span className="text-sm font-semibold">{rule.name}</span>
                    {rule.action.tags.map((tag) => (
                      <Badge key={tag} variant="outline" className="text-[10px] font-normal">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                  <div className="flex items-center gap-3 flex-wrap text-xs text-muted-foreground pl-6">
                    <span className="font-mono">{rule.mailbox}</span>
                    <span>
                      →{" "}
                      {rule.action.saveAttachment
                        ? "Accept attachment into pipeline"
                        : "Match only (do not save)"}
                    </span>
                  </div>
                </button>
                <div className="flex flex-col items-end gap-1.5 shrink-0">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-[10px] font-normal tnum">
                      <Activity className="h-3 w-3 mr-1" />
                      {rule.matchedCount} this month
                    </Badge>
                    <Switch
                      checked={rule.enabled}
                      onCheckedChange={(v) => updateRule(rule.id, { enabled: v })}
                      className="scale-90"
                      data-testid={`enable-email-${rule.id}`}
                    />
                  </div>
                  <span className="text-[11px] text-muted-foreground">
                    last matched {rule.lastMatched}
                  </span>
                </div>
              </div>

              {open && (
                <div className="border-t border-border bg-muted/20 p-3 space-y-3">
                  <div className="grid sm:grid-cols-2 gap-3">
                    <label className="block">
                      <span className="block text-[11px] font-medium text-muted-foreground mb-1">
                        Rule name
                      </span>
                      <Input
                        value={rule.name}
                        onChange={(e) => updateRule(rule.id, { name: e.target.value })}
                        className="h-8 text-sm"
                      />
                    </label>
                    <label className="block">
                      <span className="block text-[11px] font-medium text-muted-foreground mb-1">
                        Mailbox to watch
                      </span>
                      <Input
                        value={rule.mailbox}
                        onChange={(e) => updateRule(rule.id, { mailbox: e.target.value })}
                        placeholder="* for all connected mailboxes"
                        className="h-8 text-sm font-mono"
                      />
                    </label>
                  </div>
                  <div>
                    <span className="block text-[11px] font-medium text-muted-foreground mb-1.5">
                      Match conditions
                    </span>
                    <ConditionBuilder
                      root={rule.root}
                      onChange={(root) => updateRule(rule.id, { root })}
                    />
                  </div>
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <label className="inline-flex items-center gap-2 text-xs">
                      <Switch
                        checked={rule.action.saveAttachment}
                        onCheckedChange={(v) =>
                          updateRule(rule.id, {
                            action: { ...rule.action, saveAttachment: v },
                          })
                        }
                        className="scale-90"
                      />
                      Save attachment when rule matches
                    </label>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 px-2 text-xs text-muted-foreground hover:text-destructive"
                      onClick={() => removeRule(rule.id)}
                      data-testid={`delete-email-${rule.id}`}
                    >
                      <Trash2 className="h-3.5 w-3.5 mr-1" /> Delete rule
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          );
        })}
        {sorted.length === 0 && (
          <RuleBookEmptyPanel
            icon={Inbox}
            title="No ingestion rules yet"
            hint="Add a rule to accept matching email attachments into the pipeline."
          />
        )}
      </div>
    </div>
  );
}
