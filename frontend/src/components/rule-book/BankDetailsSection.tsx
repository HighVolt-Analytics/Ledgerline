import { Info, Lock } from "lucide-react";
import { Input } from "@/components/ui/input";
import { FieldLabel } from "./FieldLabel";

export type BankDetails = {
  bsb?: string;
  accountNumber: string;
  accountName: string;
  bankName: string;
  swift?: string;
  iban?: string;
};

export function maskBankField(value: string, masked: boolean) {
  if (!masked || !value || value.length <= 4) return value;
  return `••••${value.slice(-4)}`;
}

export function BankDetailsSection({
  bank,
  onChange,
  masked,
  onToggleMask,
  readOnly,
  noteFor = "Payments",
}: {
  bank: BankDetails;
  onChange?: (bank: BankDetails) => void;
  masked: boolean;
  onToggleMask?: () => void;
  readOnly?: boolean;
  noteFor?: "Payments" | "Reimbursement";
}) {
  const setField = (key: keyof BankDetails, value: string) => {
    onChange?.({ ...bank, [key]: value });
  };

  const note =
    noteFor === "Payments"
      ? "These details are used by the Payments module to execute approved payments via Stripe Connect."
      : "These details are used by the Payments module to reimburse approved staff claims via Stripe Connect.";

  return (
    <div
      className="rounded-lg border border-primary/30 bg-primary/5 p-3"
      data-testid="bank-details-section"
    >
      <div className="flex items-center justify-between gap-2 mb-2.5">
        <div className="inline-flex items-center gap-1.5 text-sm font-semibold text-primary">
          <Lock className="h-3.5 w-3.5" />
          Bank details for {noteFor === "Payments" ? "payments" : "reimbursement"}
        </div>
        {onToggleMask && (
          <button
            type="button"
            onClick={onToggleMask}
            className="text-xs text-muted-foreground hover:text-foreground underline-offset-2 hover:underline"
            data-testid="toggle-mask"
          >
            {masked ? "Show" : "Hide"}
          </button>
        )}
      </div>
      <div className="grid sm:grid-cols-2 gap-2.5">
        <FieldLabel label="BSB (AU)">
          <Input
            value={maskBankField(bank.bsb ?? "", masked)}
            onChange={(e) => setField("bsb", e.target.value)}
            readOnly={readOnly || masked}
            className="h-8 text-xs font-mono"
            placeholder="000-000"
          />
        </FieldLabel>
        <FieldLabel label="Account number">
          <Input
            value={maskBankField(bank.accountNumber, masked)}
            onChange={(e) => setField("accountNumber", e.target.value)}
            readOnly={readOnly || masked}
            className="h-8 text-xs font-mono"
            placeholder="00000000"
          />
        </FieldLabel>
        <FieldLabel label="Account name">
          <Input
            value={bank.accountName}
            onChange={(e) => setField("accountName", e.target.value)}
            readOnly={readOnly}
            className="h-8 text-xs"
            placeholder="Pty Ltd / individual name"
          />
        </FieldLabel>
        <FieldLabel label="Bank name">
          <Input
            value={bank.bankName}
            onChange={(e) => setField("bankName", e.target.value)}
            readOnly={readOnly}
            className="h-8 text-xs"
            placeholder="Bank"
          />
        </FieldLabel>
        <FieldLabel label="SWIFT (intl)">
          <Input
            value={bank.swift ?? ""}
            onChange={(e) => setField("swift", e.target.value)}
            readOnly={readOnly}
            className="h-8 text-xs font-mono"
            placeholder="—"
          />
        </FieldLabel>
        <FieldLabel label="IBAN (intl)">
          <Input
            value={bank.iban ?? ""}
            onChange={(e) => setField("iban", e.target.value)}
            readOnly={readOnly}
            className="h-8 text-xs font-mono"
            placeholder="—"
          />
        </FieldLabel>
      </div>
      <p className="mt-2.5 text-[11px] text-muted-foreground inline-flex items-start gap-1.5">
        <Info className="h-3.5 w-3.5 mt-px shrink-0 text-primary" />
        {note}
      </p>
    </div>
  );
}
