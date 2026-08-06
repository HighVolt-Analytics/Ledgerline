import { useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Shield,
  X,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { cn } from "@/lib/cn";
import { mergeCoaOptionsWithSavedValue } from "@/lib/coaAccountOptions";
import type { EmployeeMaster } from "@/lib/v4RuleBookTypes";
import { fmtAud } from "@/lib/v4MockData";
import { BankDetailsSection } from "./BankDetailsSection";
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
  const { options: ledgerOptions } = useCoaAccountOptions({
    includeEmpty: false,
  });

  const validationRules = [
    {
      label: "Sender matches a registered employee",
      ok: Boolean(emp.email) && emp.status !== "Pending verification",
    },
    {
      label: "Bank details present for reimbursement",
      ok: Boolean(emp.bank.accountNumber),
    },
  ];

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
          Outstanding Staff Advance float from advance requisitions posted to this employee&apos;s
          own sub-ledger under the parent selected here.
        </p>
      </div>

      <BankDetailsSection
        bank={emp.bank}
        onChange={(bank) => onChange({ bank })}
        masked={masked}
        onToggleMask={onToggleMask}
        noteFor="Reimbursement"
      />

      <p className="text-[11px] text-muted-foreground px-1">
        Budgets are set by GL account on{" "}
        <span className="font-medium text-foreground">Team Expenses → GL budgets</span>
        , not per employee.
      </p>

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
