import { useState } from "react";
import {
  Activity,
  AlertCircle,
  ChevronDown,
  ChevronRight,
  ChevronUp,
  Inbox,
  Lock,
  Plus,
  Search,
  Trash2,
} from "lucide-react";
import { api } from "@/api/client";
import { useToast } from "@/context/ToastContext";
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
import { RuleBookEmptyPanel } from "@/components/rule-book/RuleBookEmptyPanel";
import { Switch } from "@/components/ui/switch";
import { DEFAULT_INGESTION_MAILBOX } from "@/lib/emailIngestionRules";
import { globalPriorityContext } from "@/lib/emailIngestionRulesPriority";
import {
  employeeSenderGateTooltip,
  EMPLOYEE_BYPASS_RULE_ID,
  inferRequiresEmployeeSender,
} from "@/lib/emailIngestionRuleValidation";
import type { EmailCaptureRule } from "@/lib/v4RuleBookTypes";
import { INGEST_ACTION_ROUTE_PLACEHOLDER } from "@/lib/v4RuleBookTypes";
import { ConditionBuilder } from "@/components/rule-book/ConditionBuilder";

type PreviewMatch = {
  message_id: string;
  subject: string;
  sender: string;
  attachment: string;
  received_at: string | null;
};

export function EmailIngestionRulesEditor({
  rules,
  onChange,
  compact = false,
  mailboxScope,
  allRules = rules,
  connectedMailboxEmails = [],
  ruleWarnings = {},
}: {
  rules: EmailCaptureRule[];
  onChange: (rules: EmailCaptureRule[]) => void;
  compact?: boolean;
  mailboxScope?: string;
  allRules?: EmailCaptureRule[];
  connectedMailboxEmails?: string[];
  ruleWarnings?: Record<string, string[]>;
}) {
  const { toast } = useToast();
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [previewByRule, setPreviewByRule] = useState<Record<string, PreviewMatch[]>>({});
  const [previewBusyId, setPreviewBusyId] = useState<string | null>(null);

  const patchRule = (id: string, patch: Partial<EmailCaptureRule>) => {
    onChange(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)));
  };

  const updateRule = (id: string, patch: Partial<EmailCaptureRule>) => {
    patchRule(id, patch);
  };

  const addRule = () => {
    const id = `ec-${Date.now()}`;
    const next: EmailCaptureRule = {
      id,
      name: "New ingestion rule",
      enabled: true,
      priority: nextSerialPriority(rules),
      mailbox: mailboxScope ?? DEFAULT_INGESTION_MAILBOX,
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
      requiresEmployeeSender: false,
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

  const acceptLabel = (rule: EmailCaptureRule) =>
    rule.action.saveAttachment ? "Accept into pipeline" : "Match only (do not save)";

  const previewRule = async (rule: EmailCaptureRule) => {
    setPreviewBusyId(rule.id);
    try {
      const mailbox = mailboxScope ?? rule.mailbox;
      const result = await api.testEmailIngestionRule({
        mailbox,
        root: rule.root as unknown as Record<string, unknown>,
        rule_name: rule.name,
        lookback_days: 30,
      });
      setPreviewByRule((prev) => ({ ...prev, [rule.id]: result.matches }));
      if (result.warnings.length > 0) {
        toast({
          title: "Rule specificity warnings",
          description: result.warnings.join(" "),
          variant: "destructive",
        });
      } else {
        toast({
          title: "Preview complete",
          description: `${result.matches.length} attachment(s) would match from ${result.message_count} recent message(s).`,
        });
      }
    } catch (err) {
      toast({
        title: "Preview failed",
        description: err instanceof Error ? err.message : "Could not preview rule",
        variant: "destructive",
      });
    } finally {
      setPreviewBusyId(null);
    }
  };

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
            Rules control accept/skip only — first match wins. Workspace routing happens after the document is classified, not here.
          </p>
        </>
      ) : (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <p className="text-sm text-muted-foreground max-w-2xl">
            Gate which email attachments enter the document pipeline. First matching rule wins.
            Workspace routing happens after the document is classified, not here.
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
          const warnings = ruleWarnings[rule.id] ?? [];
          const global = globalPriorityContext(
            allRules,
            rule,
            mailboxScope ?? rule.mailbox,
            connectedMailboxEmails
          );
          const employeeGateOn = inferRequiresEmployeeSender(rule);
          const employeeGateLocked = rule.id === EMPLOYEE_BYPASS_RULE_ID;
          return (
            <Card
              key={rule.id}
              className={cn("overflow-hidden", warnings.length > 0 && "border-destructive/40")}
              data-testid={`email-rule-${rule.id}`}
            >
              {warnings.length > 0 ? (
                <div
                  className="flex flex-wrap items-start gap-1.5 border-b border-destructive/30 bg-destructive/5 px-2.5 py-1.5"
                  data-testid={`email-rule-warnings-${rule.id}`}
                >
                  <AlertCircle className="h-3.5 w-3.5 shrink-0 text-destructive mt-0.5" />
                  {warnings.map((warning) => (
                    <Badge
                      key={warning}
                      variant="outline"
                      className="text-[10px] font-normal border-destructive/40 text-destructive whitespace-normal text-left h-auto py-0.5"
                    >
                      {warning}
                    </Badge>
                  ))}
                </div>
              ) : null}
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
                    title={`Local S.No ${serial}; global priority ${global.rank} of ${global.total}`}
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
                    <div className="flex min-w-0 flex-col gap-0.5">
                      <div className="flex min-w-0 items-center gap-1.5">
                        {open ? (
                          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        )}
                        <Inbox className="h-3.5 w-3.5 text-primary shrink-0" />
                        <span className="truncate text-sm font-semibold">{rule.name}</span>
                      </div>
                      <span className="min-w-0 truncate pl-5 text-[11px] text-muted-foreground">
                        {rule.mailbox} · {acceptLabel(rule)}
                      </span>
                      <span className="pl-5 text-[10px] text-muted-foreground tnum">
                        Priority {global.rank} of {global.total} overall
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
                      </div>
                      <div className="flex items-center gap-3 flex-wrap text-xs text-muted-foreground pl-6">
                        <span className="font-mono">{rule.mailbox}</span>
                        <span>→ {acceptLabel(rule)}</span>
                        <span className="tnum">Priority {global.rank} of {global.total} overall</span>
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
                    {mailboxScope ? (
                      <label className="connect-mailbox-form-field">
                        <span>Mailbox</span>
                        <Input
                          value={
                            !rule.mailbox.trim() || rule.mailbox.trim() === "*"
                              ? "* (all mailboxes)"
                              : rule.mailbox
                          }
                          readOnly
                          className={cn("text-sm font-mono bg-muted/40", compact ? "h-8" : "h-9")}
                        />
                      </label>
                    ) : (
                      <label className="connect-mailbox-form-field">
                        <span>Mailbox</span>
                        <Input
                          value={rule.mailbox}
                          onChange={(e) => updateRule(rule.id, { mailbox: e.target.value })}
                          placeholder="* for all connected mailboxes"
                          className={cn("text-sm font-mono", compact ? "h-8" : "h-9")}
                        />
                      </label>
                    )}
                  </div>

                  <div
                    className="rounded-md border border-border bg-background/80 px-2.5 py-2 space-y-1"
                    title={employeeSenderGateTooltip(rule)}
                    data-testid={`employee-gate-${rule.id}`}
                  >
                    <label className="inline-flex items-center gap-2 text-xs">
                      {employeeGateLocked ? (
                        <Lock className="h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden />
                      ) : null}
                      <Switch
                        checked={employeeGateOn}
                        disabled={employeeGateLocked}
                        onCheckedChange={(v) =>
                          updateRule(rule.id, { requiresEmployeeSender: v })
                        }
                        className={compact ? "scale-75" : "scale-90"}
                      />
                      <span className="font-medium text-foreground">
                        Requires sender to be a registered employee
                      </span>
                    </label>
                    {employeeGateOn ? (
                      <p className="text-[11px] text-muted-foreground pl-0.5">
                        {employeeSenderGateTooltip(rule)}
                      </p>
                    ) : null}
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
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="h-8 px-2 text-xs"
                        disabled={previewBusyId === rule.id}
                        onClick={() => void previewRule(rule)}
                        data-testid={`preview-email-${rule.id}`}
                      >
                        <Search className="h-3.5 w-3.5 mr-1" />
                        {previewBusyId === rule.id ? "Previewing…" : "Preview matches"}
                      </Button>
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
                  {previewByRule[rule.id]?.length ? (
                    <div className="rounded-md border border-border bg-background/80 p-2 space-y-1">
                      <p className="text-[11px] font-medium text-muted-foreground">
                        Recent matches (dry-run, last 30 days)
                      </p>
                      {previewByRule[rule.id].slice(0, 8).map((row) => (
                        <p key={`${row.message_id}-${row.attachment}`} className="text-[11px] truncate">
                          <span className="font-mono">{row.attachment}</span>
                          {" · "}
                          {row.sender}
                          {" · "}
                          {row.subject}
                        </p>
                      ))}
                    </div>
                  ) : null}
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
