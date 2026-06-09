import { useState, type ReactNode } from "react";
import {
  ArrowRight,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  Plus,
  ShoppingCart,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { useToast } from "@/context/ToastContext";
import { INITIAL_PURCHASES } from "@/lib/v4MockData";
import type { PurchaseRule } from "@/lib/v4RuleBookTypes";
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

export function PurchaseRulesTab({
  rules,
  onChange,
}: {
  rules: PurchaseRule[];
  onChange: (rules: PurchaseRule[]) => void;
}) {
  const { toast } = useToast();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const update = (id: string, patch: Partial<PurchaseRule>) =>
    onChange(rules.map((r) => (r.id === id ? { ...r, ...patch } : r)));

  const updateMatch = (id: string, patch: Partial<PurchaseRule["matchOn"]>) =>
    onChange(
      rules.map((r) => (r.id === id ? { ...r, matchOn: { ...r.matchOn, ...patch } } : r))
    );

  const updatePost = (id: string, patch: Partial<PurchaseRule["postTo"]>) =>
    onChange(rules.map((r) => (r.id === id ? { ...r, postTo: { ...r.postTo, ...patch } } : r)));

  const removeRule = (id: string) => onChange(rules.filter((r) => r.id !== id));

  const addRule = () => {
    const id = `pr-${Date.now()}`;
    onChange([
      ...rules,
      {
        id,
        name: "New PO rule",
        enabled: true,
        matchOn: { poPrefix: "PO-" },
        postTo: {
          ledger: LEDGER_ACCOUNTS[0],
          subLedger: "",
        },
        matchedCount: 0,
      },
    ]);
    setExpandedId(id);
  };

  const testRule = (rule: PurchaseRule) => {
    const m = rule.matchOn;
    const hits = INITIAL_PURCHASES.filter((po) => {
      if (m.poPrefix && !po.id.startsWith(m.poPrefix)) return false;
      if (m.poRegex) {
        try {
          if (!new RegExp(m.poRegex).test(po.id)) return false;
        } catch {
          return false;
        }
      }
      if (m.vendorContains && !po.vendor.toLowerCase().includes(m.vendorContains.toLowerCase())) {
        return false;
      }
      return !!(m.poPrefix || m.poRegex || m.vendorContains);
    });
    toast({
      title: `Tested “${rule.name}”`,
      description: hits.length
        ? `Catches ${hits.length} current PO(s): ${hits.map((p) => p.id).join(", ")}`
        : "No current POs match this rule's prefix/regex.",
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground max-w-2xl">
          Code POs, GRNs, and commercial invoices that reference a PO to the right ledger and
          sub-ledger.
        </p>
        <Button size="sm" onClick={addRule} data-testid="button-new-purchase-rule">
          <Plus className="h-4 w-4 mr-1" /> New Rule
        </Button>
      </div>

      <div className="space-y-3">
        {rules.map((rule) => {
          const open = expandedId === rule.id;
          const m = rule.matchOn;
          return (
            <Card key={rule.id} className="overflow-hidden" data-testid={`purchase-rule-${rule.id}`}>
              <div className="flex items-start gap-3 p-3">
                <button
                  type="button"
                  className="flex-1 min-w-0 text-left"
                  onClick={() => setExpandedId(open ? null : rule.id)}
                  data-testid={`toggle-purchase-${rule.id}`}
                >
                  <div className="flex items-center gap-2 flex-wrap mb-1.5">
                    {open ? (
                      <ChevronDown className="h-4 w-4 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    )}
                    <ShoppingCart className="h-4 w-4 text-primary shrink-0" />
                    <span className="text-sm font-semibold">{rule.name}</span>
                  </div>
                  <div className="flex items-center gap-2 flex-wrap pl-6">
                    {m.poPrefix && <MatchChip>prefix {m.poPrefix}</MatchChip>}
                    {m.poRegex && <MatchChip>regex {m.poRegex}</MatchChip>}
                    {m.vendorContains && <MatchChip>vendor ~ {m.vendorContains}</MatchChip>}
                    {m.grnLinkedToPo && (
                      <Badge variant="outline" className="text-[10px] font-normal">
                        GRN-linked
                      </Badge>
                    )}
                    {m.invoiceReferencesPo && (
                      <Badge variant="outline" className="text-[10px] font-normal">
                        Invoice-ref
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
                    data-testid={`enable-purchase-${rule.id}`}
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
                      <FieldLabel label="PO prefix">
                        <Input
                          value={m.poPrefix ?? ""}
                          onChange={(e) => updateMatch(rule.id, { poPrefix: e.target.value })}
                          className="h-8 text-xs font-mono"
                          placeholder="PO-CLOUD-"
                        />
                      </FieldLabel>
                      <FieldLabel label="PO regex (optional)">
                        <Input
                          value={m.poRegex ?? ""}
                          onChange={(e) => updateMatch(rule.id, { poRegex: e.target.value })}
                          className="h-8 text-xs font-mono"
                          placeholder="^PO-MKT-2026-"
                        />
                      </FieldLabel>
                      <FieldLabel label="Vendor narrowing">
                        <Input
                          value={m.vendorContains ?? ""}
                          onChange={(e) => updateMatch(rule.id, { vendorContains: e.target.value })}
                          className="h-8 text-xs"
                          placeholder="vendor fragment"
                        />
                      </FieldLabel>
                    </div>
                    <div className="flex flex-wrap gap-5 mt-3">
                      <label className="inline-flex items-center gap-2 text-xs">
                        <Switch
                          checked={!!m.grnLinkedToPo}
                          onCheckedChange={(v) => updateMatch(rule.id, { grnLinkedToPo: v })}
                          className="scale-90"
                        />
                        Apply to GRNs linked to matching POs
                      </label>
                      <label className="inline-flex items-center gap-2 text-xs">
                        <Switch
                          checked={!!m.invoiceReferencesPo}
                          onCheckedChange={(v) => updateMatch(rule.id, { invoiceReferencesPo: v })}
                          className="scale-90"
                        />
                        Apply to invoices referencing matching POs
                      </label>
                    </div>
                  </div>

                  <div>
                    <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
                      Post to
                    </h4>
                    <div className="grid sm:grid-cols-2 gap-2.5">
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
                          placeholder="cost centre"
                        />
                      </FieldLabel>
                    </div>
                    <p className="text-[11px] text-muted-foreground mt-2">
                      Tax and payable accounts are set org-wide on the Posting tab.
                    </p>
                  </div>

                  <div className="flex items-center justify-between">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 text-xs"
                      onClick={(e) => {
                        e.stopPropagation();
                        testRule(rule);
                      }}
                      data-testid={`test-purchase-${rule.id}`}
                    >
                      <FlaskConical className="h-3.5 w-3.5 mr-1" /> Test against current POs
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-8 px-2 text-xs text-muted-foreground hover:text-destructive"
                      onClick={() => removeRule(rule.id)}
                      data-testid={`delete-purchase-${rule.id}`}
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
            No purchase rules yet.
          </Card>
        )}
      </div>
    </div>
  );
}
