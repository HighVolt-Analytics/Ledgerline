import { ArrowRight } from "lucide-react";
import { Select } from "@/components/ui/select";
import { teamExpensePostingPreview } from "@/lib/teamExpensePosting";
import {
  TEAM_EXPENSE_KINDS,
  TEAM_EXPENSE_KIND_LABELS,
  type TeamExpenseKind,
} from "@/lib/v4RuleBookTypes";

const KIND_OPTIONS = TEAM_EXPENSE_KINDS.map((kind) => ({
  value: kind,
  label: TEAM_EXPENSE_KIND_LABELS[kind],
}));

export function ClaimKindField({
  kind,
  expenseLedger,
  advanceLedger,
  settlementLedger,
  claimAmount = 0,
  advanceAvailable = 0,
  disabled,
  onChange,
}: {
  kind: TeamExpenseKind;
  expenseLedger: string;
  advanceLedger: string;
  settlementLedger: string;
  claimAmount?: number;
  advanceAvailable?: number;
  disabled: boolean;
  onChange: (kind: TeamExpenseKind) => void;
}) {
  const preview = teamExpensePostingPreview(kind, {
    expenseLedger,
    advanceLedger,
    settlementLedger,
    claimAmount,
    advanceAvailable,
  });

  return (
    <div className="mt-3 rounded-md border border-border p-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="text-[11px] text-muted-foreground uppercase tracking-wide">
          Claim kind
        </div>
        <Select
          value={kind}
          onValueChange={(next) => onChange(next as TeamExpenseKind)}
          options={KIND_OPTIONS}
          disabled={disabled}
          size="sm"
          className="w-[13.5rem] text-xs"
          data-testid="select-claim-kind"
        />
      </div>
      <div
        className="mt-2 flex items-center gap-2 text-xs flex-wrap"
        data-testid="claim-posting-preview"
      >
        <span className="text-muted-foreground">Dr</span>
        <span className="font-medium">{preview.debit}</span>
        <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
        <span className="text-muted-foreground">Cr</span>
        <span className="font-medium">{preview.credit}</span>
      </div>
      <p className="mt-1 text-[11px] text-muted-foreground">{preview.note}</p>
    </div>
  );
}
