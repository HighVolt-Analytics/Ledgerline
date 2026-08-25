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
import { cn } from "@/lib/cn";
import { RuleBookEmptyPanel } from "./RuleBookEmptyPanel";
import { Switch } from "@/components/ui/switch";
import { DEFAULT_MAILBOX } from "@/lib/v4RuleBookMockData";
import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";
import { INGEST_ACTION_ROUTE_PLACEHOLDER } from "@/lib/v4RuleBookTypes";
import { ConditionBuilder } from "@/components/rule-book/ConditionBuilder";

export function IngestionTab({
  rules,
  onChange,
  compact = false,
}: {
  rules: EmailCaptureRule[];
  onChange: (rules: EmailCaptureRule[]) => void;
  compact?: boolean;
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

  const routeLabel = (rule: EmailCaptureRule) =>
    rule.action.saveAttachment ? "Accept attachment into pipeline" : "Match only (do not save)";

  return (
    <div className={compact ? "space-y-2" : "space-y-4"}>
      {compact ? (
        <>
          <div className="flex items-center justify-between gap-3">
            <h3 className="text-sm font-semibold leading-none">Ingestion rules</h3>
            <Button type="button" size="sm" className="shrink-0" onClick={addRule} data-testid="button-new-email-rule">
              <Plus className="h-4 w-4 mr-1" /> New Rule
            </Button>
          </div>
          <p className="text-xs text-muted-foreground">
            Rules run in S.No order — first match wins. Matching attachments are accepted for OCR only.
          </p>
        </>
      ) : (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-sm text-muted-foreground max-w-2xl">
            Gate which email attachments enter the document pipeline. Rules are checked in S.No order — first match wins. Matching rules accept attachments for OCR only — they do not route to Purchase, Expenses, or Team workspaces. Upload and WhatsApp use separate channel gates.
          </p>
          <Button type="button" size="sm" className="shrink-0" onClick={addRule} data-testid="button-new-email-rule">
            <Plus className="h-4 w-4 mr-1" /> New Rule
          </Button>
        </div>
      )}

      <div className={compact ? "space-y-1.5" : "space-y-3"}>
        {sorted.map((rule, index) => {
          const open = expandedId === rule.id;
          const serial = index + 1;
          return (
            <Card key={rule.id} className="overflow-hidden" data-testid={`email-rule-${rule.id}`}>
              <div
                className={cn(
                  "flex items-center",
                  compact ? "gap-2 px-2.5 py-1.5" : "gap-3 p-3"
                )}
              >
                <div className="flex items-center gap-1 shrink-0">
                  <div className={cn("flex flex-col", compact && "-space-y-0.5")}>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={cn(
                        "p-0 text-muted-foreground",
                        compact ? "h-3.5 w-3.5 [&_svg]:size-3" : "h-5 w-5"
                      )}
                      disabled={index === 0}
                      onClick={() => moveRule(rule.id, -1)}
                      aria-label={`Move rule ${serial} up`}
                      data-testid={`move-up-email-${rule.id}`}
                    >
                      <ChevronUp className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} />
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className={cn(
                        "p-0 text-muted-foreground",
                        compact ? "h-3.5 w-3.5 [&_svg]:size-3" : "h-5 w-5"
                      )}
                      disabled={index === sorted.length - 1}
                      onClick={() => moveRule(rule.id, 1)}
                      aria-label={`Move rule ${serial} down`}
                      data-testid={`move-down-email-${rule.id}`}
                    >
                      <ChevronDown className={compact ? "h-3 w-3" : "h-3.5 w-3.5"} />
                    </Button>
                  </div>
                  <span
                    className={cn(
                      "inline-flex items-center justify-center rounded-md bg-muted px-1 font-semibold tnum",
                      compact ? "h-5 min-w-5 text-[10px]" : "h-6 min-w-6 text-xs"
                    )}
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
                  {compact ? (
                    <div className="flex min-w-0 items-center gap-1.5">
                      {open ? (
                        <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      )}
                      <Inbox className="h-3.5 w-3.5 text-primary shrink-0" />
                      <span className="truncate text-sm font-semibold">{rule.name}</span>
                      <span className="min-w-0 truncate text-[11px] text-muted-foreground">
                        {rule.mailbox} → {routeLabel(rule)}
                      </span>
                    </div>
                  ) : (
                    <>
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
                        <span>→ {routeLabel(rule)}</span>
                      </div>
                    </>
                  )}
                </button>
                <div className={cn("flex items-end shrink-0", compact ? "items-center" : "flex-col gap-1")}>
                  <div className="flex items-center gap-2">
                    {!compact ? (
                      <Badge variant="outline" className="text-[10px] font-normal tnum">
                        <Activity className="h-3 w-3 mr-1" />
                        {rule.matchedCount} this month
                      </Badge>
                    ) : null}
                    <Switch
                      checked={rule.enabled}
                      onCheckedChange={(v) => updateRule(rule.id, { enabled: v })}
                      className={compact ? "scale-75 origin-right" : "scale-90"}
                      data-testid={`enable-email-${rule.id}`}
                    />
                  </div>
                  {!compact ? (
                    <span className="text-[11px] text-muted-foreground">
                      last matched {rule.lastMatched}
                    </span>
                  ) : null}
                </div>
              </div>

              {open && (
                <div
                  className={cn(
                    "border-t border-border bg-muted/20",
                    compact ? "space-y-2 p-2.5" : "space-y-3 p-3"
                  )}
                >
                  <div className="connect-mailbox-form-grid">
                    <label className="connect-mailbox-form-field">
                      <span>Rule name</span>
                      <Input
                        value={rule.name}
                        onChange={(e) => updateRule(rule.id, { name: e.target.value })}
                        className={cn("text-sm", compact ? "h-8" : "h-9")}
                      />
                    </label>
                    <label className="connect-mailbox-form-field">
                      <span>Mailbox</span>
                      <Input
                        value={rule.mailbox}
                        onChange={(e) => updateRule(rule.id, { mailbox: e.target.value })}
                        placeholder="* for all connected mailboxes"
                        className={cn("text-sm font-mono", compact ? "h-8" : "h-9")}
                      />
                    </label>
                  </div>
                  <div className="min-w-0 space-y-1">
                    <span className="block h-4 text-xs leading-4 text-muted-foreground">
                      Match conditions
                    </span>
                    <ConditionBuilder
                      compact={compact}
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
                        className={compact ? "scale-75" : "scale-90"}
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
