import { useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Plus,
  Shield,
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NumericInput } from "@/components/ui/numeric-input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { cn } from "@/lib/cn";
import {
  defaultExpensePostingLedger,
  mergeCoaOptionsWithSavedValue,
} from "@/lib/coaAccountOptions";
import type { EmployeeMaster } from "@/lib/v4RuleBookTypes";
import { fmtAud } from "@/lib/v4MockData";
import { BankDetailsSection } from "./BankDetailsSection";
import { BudgetProgressBar } from "./BudgetProgressBar";
import { FieldLabel } from "./FieldLabel";

const EMPLOYEE_STATUS_OPTIONS = ["Active", "Suspended", "Pending verification"] as const;

export function EmployeeDetailPanel({
  emp,
  onChange,
  masked,
  onToggleMask,
}: {
  emp: EmployeeMaster;
  onChange: (patch: Partial<EmployeeMaster>) => void;
  masked: boolean;
  onToggleMask?: () => void;
}) {
  const [rulesOpen, setRulesOpen] = useState(false);
  const { allAccounts, options: ledgerOptions } = useCoaAccountOptions({
    includeEmpty: false,
  });

  const validationRules = [
    {
      label: "Sender matches a registered employee",
      ok: Boolean(emp.email) && emp.status !== "Pending verification",
    },
    {
      label: "MTD spend + claim ≤ monthly spending limit",
      ok: emp.mtdSpent <= emp.budget.monthly,
    },
    {
      label: "Category cap not exceeded",
      ok:
        emp.budget.categories.length > 0
          ? emp.mtdSpent <= emp.budget.categories.reduce((sum, c) => sum + c.cap, 0)
          : true,
    },
    {
      label: "Bank details present for reimbursement",
      ok: Boolean(emp.bank.accountNumber),
    },
  ];

  const updateCategory = (index: number, patch: Partial<{ ledger: string; cap: number }>) => {
    onChange({
      budget: {
        ...emp.budget,
        categories: emp.budget.categories.map((c, i) => (i === index ? { ...c, ...patch } : c)),
      },
    });
  };

  const addCategoryCap = () => {
    onChange({
      budget: {
        ...emp.budget,
        categories: [
          ...emp.budget.categories,
          { ledger: defaultExpensePostingLedger(allAccounts), cap: 200 },
        ],
      },
    });
  };

  const removeCategoryCap = (index: number) => {
    onChange({
      budget: {
        ...emp.budget,
        categories: emp.budget.categories.filter((_, i) => i !== index),
      },
    });
  };

  return (
    <div className="bg-muted/20 p-4 space-y-4" data-testid={`employee-detail-${emp.id}`}>
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          Identity
        </h4>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
          <FieldLabel label="Name">
            <Input
              value={emp.name}
              onChange={(e) => onChange({ name: e.target.value })}
              className="h-8 text-sm"
            />
          </FieldLabel>
          <FieldLabel label="Email">
            <Input
              value={emp.email}
              onChange={(e) => onChange({ email: e.target.value })}
              className="h-8 text-xs font-mono"
            />
          </FieldLabel>
          <FieldLabel label="Status">
            <Select
              value={emp.status}
              onValueChange={(status) => onChange({ status })}
              options={toSelectOptions(EMPLOYEE_STATUS_OPTIONS)}
              size="sm"
              className="w-full text-xs"
            />
          </FieldLabel>
          <FieldLabel label="WhatsApp / Mobile 1">
            <Input
              value={emp.whatsappNumber}
              onChange={(e) => onChange({ whatsappNumber: e.target.value })}
              className="h-8 text-xs font-mono"
            />
          </FieldLabel>
          <FieldLabel label="WhatsApp / Mobile 2">
            <Input
              value={emp.whatsappNumber2 ?? ""}
              onChange={(e) => onChange({ whatsappNumber2: e.target.value })}
              className="h-8 text-xs font-mono"
            />
          </FieldLabel>
          <FieldLabel label="Viber (optional)">
            <Input
              value={emp.viberNumber ?? ""}
              onChange={(e) => onChange({ viberNumber: e.target.value })}
              className="h-8 text-xs font-mono"
            />
          </FieldLabel>
        </div>
      </div>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          Organisation
        </h4>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
          <FieldLabel label="Date of joining">
            <Input
              value={emp.dateOfJoining ?? ""}
              onChange={(e) => onChange({ dateOfJoining: e.target.value })}
              placeholder="YYYY-MM-DD"
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Department">
            <Input
              value={emp.department ?? ""}
              onChange={(e) => onChange({ department: e.target.value })}
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Designation">
            <Input
              value={emp.role}
              onChange={(e) => onChange({ role: e.target.value })}
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Location">
            <Input
              value={emp.location ?? ""}
              onChange={(e) => onChange({ location: e.target.value })}
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Division">
            <Input
              value={emp.division ?? ""}
              onChange={(e) => onChange({ division: e.target.value })}
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Supervisor 1">
            <Input
              value={emp.supervisor1 ?? ""}
              onChange={(e) => onChange({ supervisor1: e.target.value })}
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Supervisor 2">
            <Input
              value={emp.supervisor2 ?? ""}
              onChange={(e) => onChange({ supervisor2: e.target.value })}
              className="h-8 text-xs"
            />
          </FieldLabel>
        </div>
      </div>

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          Advance posting
        </h4>
        <div className="grid sm:grid-cols-2 gap-2.5">
          <FieldLabel label="Advance parent ledger">
            <Select
              value={emp.advanceParentLedger}
              onValueChange={(advanceParentLedger) => onChange({ advanceParentLedger })}
              options={mergeCoaOptionsWithSavedValue(ledgerOptions, emp.advanceParentLedger)}
              size="sm"
              className="w-full text-xs"
              data-testid={`employee-advance-parent-${emp.id}`}
            />
          </FieldLabel>
          <FieldLabel label="Sub-ledger (created automatically)">
            <Input
              value={emp.advanceSubLedger || "Created when you save"}
              readOnly
              disabled
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Net advance outstanding">
            <Input
              value={fmtAud(emp.advanceBalance ?? 0)}
              readOnly
              disabled
              className="h-8 text-xs tnum"
              data-testid={`employee-advance-balance-${emp.id}`}
            />
          </FieldLabel>
        </div>
        <p className="text-[11px] text-muted-foreground mt-1.5">
          Advances given − expenses cleared against advance, from this employee&apos;s Staff Advance
          sub-ledger. Advances and expenses settled against them post to this employee&apos;s own
          sub-ledger under the parent selected here.
        </p>
      </div>

      <BankDetailsSection
        bank={emp.bank}
        onChange={(bank) => onChange({ bank })}
        masked={masked}
        onToggleMask={onToggleMask}
        noteFor="Reimbursement"
      />

      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground mb-2">
          Spending limits
        </h4>
        <div className="grid sm:grid-cols-3 gap-2.5 mb-3">
          <FieldLabel label="Monthly ($)">
            <NumericInput
              value={emp.budget.monthly}
              onValueChange={(monthly) =>
                onChange({ budget: { ...emp.budget, monthly: monthly ?? 0 } })
              }
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Quarterly ($)">
            <NumericInput
              value={emp.budget.quarterly}
              onValueChange={(quarterly) =>
                onChange({ budget: { ...emp.budget, quarterly: quarterly ?? 0 } })
              }
              className="h-8 text-xs"
            />
          </FieldLabel>
          <FieldLabel label="Annual ($)">
            <NumericInput
              value={emp.budget.annual}
              onValueChange={(annual) =>
                onChange({ budget: { ...emp.budget, annual: annual ?? 0 } })
              }
              className="h-8 text-xs"
            />
          </FieldLabel>
        </div>
        <div className="grid sm:grid-cols-3 gap-3 mb-3">
          <BudgetProgressBar
            value={emp.mtdSpent}
            max={emp.budget.monthly}
            label="MTD vs monthly"
          />
          <BudgetProgressBar
            value={emp.qtdSpent}
            max={emp.budget.quarterly}
            label="QTD vs quarterly"
          />
          <BudgetProgressBar value={emp.ytdSpent} max={emp.budget.annual} label="YTD vs annual" />
        </div>

        <div>
          <div className="flex items-center gap-3 mb-2 flex-wrap">
            <span className="text-[11px] font-medium text-muted-foreground shrink-0">
              Per-category caps
            </span>
            {emp.budget.categories.length === 0 && (
              <span className="text-xs text-muted-foreground italic">No caps set</span>
            )}
            <Button
              variant="outline"
              size="sm"
              className="h-7 px-2 text-xs shrink-0 ml-auto"
              onClick={addCategoryCap}
              data-testid={`add-cap-${emp.id}`}
            >
              <Plus className="h-3.5 w-3.5 mr-1" />
              Cap
            </Button>
          </div>

          {emp.budget.categories.length > 0 && (
            <div className="flex flex-col items-start gap-2">
              {emp.budget.categories.map((cat, index) => (
                <div
                  key={`${emp.id}-cap-${index}`}
                  className="flex items-center gap-1.5 w-fit rounded-md border border-border bg-background pl-1.5 pr-1 py-1"
                >
                  <Select
                    value={cat.ledger}
                    onValueChange={(ledger) => updateCategory(index, { ledger })}
                    options={mergeCoaOptionsWithSavedValue(ledgerOptions, cat.ledger)}
                    size="sm"
                    className="w-[10.5rem] text-xs border-0 shadow-none bg-transparent"
                  />
                  <div className="flex items-center gap-1.5 ml-3 pl-3 border-l border-border/50 shrink-0">
                    <span className="text-[10px] text-muted-foreground">$</span>
                    <NumericInput
                      value={cat.cap}
                      onValueChange={(cap) => updateCategory(index, { cap: cap ?? 0 })}
                      wrapperClassName="w-[4rem] shrink-0"
                      className="h-7 text-xs border-0 shadow-none bg-muted/40"
                    />
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0 shrink-0 text-muted-foreground hover:text-destructive"
                    onClick={() => removeCategoryCap(index)}
                    aria-label="Remove cap"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <Card className="overflow-hidden">
        <button
          type="button"
          className="w-full flex items-center justify-between gap-2 p-2.5 text-left"
          onClick={() => setRulesOpen((v) => !v)}
          data-testid={`validation-toggle-${emp.id}`}
        >
          <div className="flex items-center gap-2 text-xs font-semibold">
            <Shield className="h-3.5 w-3.5 text-primary" />
            Validation rules
          </div>
          {rulesOpen ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </button>
        {rulesOpen && (
          <div className="border-t border-border p-3 space-y-1.5">
            {validationRules.map((rule) => (
              <div key={rule.label} className="flex items-center gap-2 text-xs">
                {rule.ok ? (
                  <Check className="h-4 w-4 text-[hsl(var(--chart-1))]" />
                ) : (
                  <X className="h-4 w-4 text-destructive" />
                )}
                <span className={cn(!rule.ok && "text-destructive")}>{rule.label}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <p className="text-[11px] text-muted-foreground px-1">
        Use Save employee in the panel footer to persist changes. Removing an employee is available
        there as well.
      </p>
    </div>
  );
}
