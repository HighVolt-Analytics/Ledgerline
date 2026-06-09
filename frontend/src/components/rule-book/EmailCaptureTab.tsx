import { useState } from "react";
import { createPortal } from "react-dom";
import {
  Activity,
  Check,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  GripVertical,
  Mail,
  Paperclip,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import { evalConditionGroup } from "@/lib/v4RuleBookLogic";
import { DEFAULT_MAILBOX, SAMPLE_EMAILS } from "@/lib/v4RuleBookMockData";
import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";
import { ROUTE_TARGETS } from "@/lib/v4RuleBookTypes";
import { ConditionBuilder } from "./ConditionBuilder";

export function EmailCaptureTab({
  rules,
  onChange,
}: {
  rules: EmailCaptureRule[];
  onChange: (rules: EmailCaptureRule[]) => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(rules[0]?.id ?? null);
  const [testRule, setTestRule] = useState<EmailCaptureRule | null>(null);

  const updateRule = (id: string, patch: Partial<EmailCaptureRule>) => {
    onChange(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  const addRule = () => {
    const id = `ec-${Date.now()}`;
    const next: EmailCaptureRule = {
      id,
      name: "New capture rule",
      enabled: true,
      priority: rules.length + 1,
      mailbox: DEFAULT_MAILBOX,
      root: { type: "group", operator: "AND", children: [{ type: "condition", field: "subject", operator: "contains", value: "" }] },
      action: { saveAttachment: true, routeTo: ROUTE_TARGETS[0], tags: [] },
      matchedCount: 0,
      lastMatched: "—",
    };
    onChange([...rules, next]);
    setExpandedId(id);
  };

  const removeRule = (id: string) => onChange(rules.filter((r) => r.id !== id));

  const sorted = [...rules].sort((a, b) => a.priority - b.priority);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground max-w-2xl">
          Decide which inbound emails get their attachments saved into the document pipeline. Rules
          evaluate by priority (lower number first).
        </p>
        <Button size="sm" onClick={addRule} data-testid="button-new-email-rule">
          <Plus className="h-4 w-4 mr-1" /> New Rule
        </Button>
      </div>

      <div className="space-y-3">
        {sorted.map((rule) => {
          const open = expandedId === rule.id;
          return (
            <Card key={rule.id} className="overflow-hidden" data-testid={`email-rule-${rule.id}`}>
              <div className="flex items-start gap-3 p-3">
                <div className="flex items-center gap-1.5 pt-0.5">
                  <GripVertical className="h-4 w-4 text-muted-foreground/50" aria-hidden />
                  <span className="inline-flex h-6 w-6 items-center justify-center rounded-md bg-muted text-xs font-semibold tnum">
                    {rule.priority}
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
                    <Mail className="h-4 w-4 text-primary shrink-0" />
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
                      → Save & route to{" "}
                      <span className="font-medium text-foreground">{rule.action.routeTo}</span>
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
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span>last matched {rule.lastMatched}</span>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-[11px]"
                      onClick={() => setTestRule(rule)}
                      data-testid={`test-email-${rule.id}`}
                    >
                      <FlaskConical className="h-3 w-3 mr-1" /> Test
                    </Button>
                  </div>
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
                  <div className="grid sm:grid-cols-2 gap-3 items-end">
                    <label className="block">
                      <span className="block text-[11px] font-medium text-muted-foreground mb-1">
                        Route attachment to
                      </span>
                      <Select
                        value={rule.action.routeTo}
                        onValueChange={(routeTo) =>
                          updateRule(rule.id, {
                            action: { ...rule.action, routeTo },
                          })
                        }
                        options={toSelectOptions(ROUTE_TARGETS)}
                        className="w-full"
                      />
                    </label>
                    <div className="flex items-center justify-between gap-3">
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
                        Save attachment
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
                </div>
              )}
            </Card>
          );
        })}
        {sorted.length === 0 && (
          <Card className="p-6 text-center text-sm text-muted-foreground">
            No email capture rules yet.
          </Card>
        )}
      </div>

      {testRule &&
        createPortal(
          <div className="app-modal-root" role="presentation">
            <button
              type="button"
              className="app-modal-backdrop"
              aria-label="Close dialog"
              onClick={() => setTestRule(null)}
            />
            <div
              role="dialog"
              aria-modal="true"
              className="app-modal-panel max-w-lg p-6 space-y-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-base font-semibold leading-none">
                    Test &ldquo;{testRule.name}&rdquo;
                  </h3>
                  <p className="text-xs text-muted-foreground mt-2">
                    Each sample email is evaluated against this rule&apos;s condition tree.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setTestRule(null)}
                  aria-label="Close"
                  className="rounded-sm opacity-70 hover:opacity-100 shrink-0"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="space-y-2 max-h-80 overflow-y-auto pr-1">
                {SAMPLE_EMAILS.map((email) => {
                  const fires = testRule.enabled && evalConditionGroup(email, testRule.root);
                  return (
                    <div
                      key={email.id}
                      className={cn(
                        "rounded-lg border p-3",
                        fires
                          ? "border-primary/30 bg-primary/10"
                          : "border-border bg-card"
                      )}
                      data-testid={`test-result-${email.id}`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-sm font-medium truncate">
                            {email.subject || (
                              <span className="text-muted-foreground italic">(no subject)</span>
                            )}
                          </div>
                          <div className="text-xs text-muted-foreground font-mono truncate">
                            {email.from}
                          </div>
                          <div className="text-[11px] text-muted-foreground mt-0.5">
                            {email.attachment_name ? (
                              <span className="inline-flex items-center gap-1">
                                <Paperclip className="h-3 w-3 shrink-0" />
                                {email.attachment_name}
                                <span className="opacity-70">· {email.attachment_mime}</span>
                              </span>
                            ) : (
                              "no attachment"
                            )}
                          </div>
                        </div>
                        <Badge
                          className={cn(
                            "shrink-0 border-0",
                            fires
                              ? "bg-primary text-primary-foreground"
                              : "bg-muted text-muted-foreground"
                          )}
                        >
                          {fires ? (
                            <>
                              <Check className="h-3 w-3 mr-1" /> Fires
                            </>
                          ) : (
                            <>
                              <X className="h-3 w-3 mr-1" /> No match
                            </>
                          )}
                        </Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>,
          document.body
        )}
    </div>
  );
}
