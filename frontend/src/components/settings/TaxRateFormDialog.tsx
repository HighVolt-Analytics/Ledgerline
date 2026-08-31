import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { Plus, Trash2, X } from "lucide-react";

import type { OrgTaxRateRow, OrgTaxRateWrite } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  formatTaxPercent,
  isTaxRateReportType,
  parseTaxRateInput,
  TAX_RATE_TYPE_OPTIONS,
  totalTaxRate,
  type TaxRateReportType,
} from "@/lib/taxRates";

type LocalComponent = { name: string; rateInput: string };

type TaxRateFormDialogProps = {
  open: boolean;
  busy?: boolean;
  existingNames: string[];
  editing?: OrgTaxRateRow | null;
  onClose: () => void;
  onSave: (row: OrgTaxRateWrite) => void;
};

function emptyComponent(): LocalComponent {
  return { name: "", rateInput: "" };
}

function fromRow(row: OrgTaxRateRow): LocalComponent[] {
  if (!row.components.length) return [emptyComponent()];
  return row.components.map((item) => ({
    name: item.name,
    rateInput: Number.isFinite(item.rate) ? String(item.rate) : "",
  }));
}

export function TaxRateFormDialog({
  open,
  busy = false,
  existingNames,
  editing = null,
  onClose,
  onSave,
}: TaxRateFormDialogProps) {
  const titleId = useId();
  const isEdit = Boolean(editing);
  const [displayName, setDisplayName] = useState("");
  const [taxType, setTaxType] = useState<TaxRateReportType>("SALES");
  const [components, setComponents] = useState<LocalComponent[]>([emptyComponent()]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setDisplayName(editing?.display_name ?? "");
    const nextType = editing?.tax_type ?? "";
    setTaxType(isTaxRateReportType(nextType) ? nextType : "SALES");
    setComponents(editing ? fromRow(editing) : [emptyComponent()]);
    setError(null);
  }, [open, editing]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const parsedRates = components.map((row) => parseTaxRateInput(row.rateInput) ?? 0);
  const total = totalTaxRate(parsedRates.map((rate) => ({ rate })));

  const updateComponent = (index: number, patch: Partial<LocalComponent>) => {
    setComponents((prev) => prev.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const name = displayName.trim();
    if (!name) {
      setError("Enter a tax rate display name.");
      return;
    }
    if (name.length > 50) {
      setError("Display name is limited to 50 characters.");
      return;
    }
    const skipName = editing?.display_name.trim().toLowerCase() ?? "";
    if (
      existingNames.some(
        (item) => item.toLowerCase() === name.toLowerCase() && item.toLowerCase() !== skipName
      )
    ) {
      setError("A tax rate with this name already exists.");
      return;
    }
    const cleaned = components
      .map((row) => ({
        name: row.name.trim(),
        rate: parseTaxRateInput(row.rateInput),
      }))
      .filter((row) => row.name || row.rate != null);
    if (!cleaned.length) {
      setError("Add at least one tax component.");
      return;
    }
    if (cleaned.some((row) => !row.name)) {
      setError("Each tax component needs a name.");
      return;
    }
    if (cleaned.some((row) => row.rate == null || row.rate < 0 || row.rate > 100)) {
      setError("Each tax component needs a percentage between 0 and 100.");
      return;
    }
    setError(null);
    onSave({
      display_name: name,
      tax_type: taxType,
      components: cleaned.map((row) => ({ name: row.name, rate: row.rate as number })),
    });
  };

  return createPortal(
    <div className="app-modal-root" role="presentation" data-testid="dialog-tax-rate-form">
      <button
        type="button"
        className="app-modal-backdrop cursor-pointer"
        aria-label="Close dialog"
        disabled={busy}
        onClick={() => {
          if (!busy) onClose();
        }}
      />
      <form
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="app-modal-panel add-tax-rate-dialog space-y-5 p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id={titleId} className="text-lg font-semibold leading-none">
            {isEdit ? "Edit Tax Rate" : "Add New Tax Rate"}
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="cursor-pointer rounded-md p-1 text-muted-foreground opacity-80 transition-opacity hover:opacity-100 disabled:cursor-not-allowed"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-1.5">
          <label htmlFor="tax-rate-display-name" className="text-sm font-medium">
            Tax Rate Display Name
          </label>
          <p className="text-xs text-muted-foreground">
            The name as you would like it to appear (limited to 50 characters)
          </p>
          <Input
            id="tax-rate-display-name"
            data-testid="input-tax-rate-name"
            value={displayName}
            maxLength={50}
            onChange={(e) => setDisplayName(e.target.value)}
            autoFocus
          />
        </div>

        <div className="space-y-1.5">
          <label htmlFor="tax-rate-type" className="text-sm font-medium">
            Tax Type
          </label>
          <p className="text-xs text-muted-foreground">
            Choose how this tax rate will be reported in your Activity Statement
          </p>
          <Select
            id="tax-rate-type"
            value={taxType}
            onValueChange={(value) => setTaxType(value as TaxRateReportType)}
            options={TAX_RATE_TYPE_OPTIONS.map((option) => ({
              value: option.value,
              label: option.label,
            }))}
            className="w-full cursor-pointer"
            data-testid="select-tax-rate-type"
            size="md"
          />
        </div>

        <div className="space-y-3 border-t border-border pt-4">
          {components.map((row, index) => (
            <div key={index} className="flex items-center gap-2">
              <Input
                value={row.name}
                onChange={(e) => updateComponent(index, { name: e.target.value })}
                placeholder="Component name"
                className="flex-1"
                data-testid={`input-tax-component-name-${index}`}
                maxLength={50}
              />
              <div className="relative w-24 shrink-0">
                <Input
                  inputMode="decimal"
                  value={row.rateInput}
                  onChange={(e) => {
                    const next = e.target.value;
                    if (next === "" || /^\d{0,3}(\.\d{0,4})?$/.test(next)) {
                      updateComponent(index, { rateInput: next });
                    }
                  }}
                  placeholder=""
                  className="pr-7 tnum text-right"
                  data-testid={`input-tax-component-rate-${index}`}
                  aria-label="Tax component percent"
                />
                <span className="pointer-events-none absolute inset-y-0 right-2 flex items-center text-xs text-muted-foreground">
                  %
                </span>
              </div>
              {components.length > 1 ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 shrink-0 cursor-pointer text-muted-foreground hover:text-destructive"
                  onClick={() => setComponents((prev) => prev.filter((_, i) => i !== index))}
                  aria-label="Remove component"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </Button>
              ) : null}
            </div>
          ))}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-8 cursor-pointer px-2 text-primary"
              onClick={() => setComponents((prev) => [...prev, emptyComponent()])}
              data-testid="button-add-tax-component"
            >
              <Plus className="h-3.5 w-3.5" />
              Add a Component
            </Button>
            <p className="text-sm">
              <span className="text-muted-foreground">Total tax rate</span>{" "}
              <span className="tnum font-medium">{formatTaxPercent(total)}</span>
            </p>
          </div>
        </div>

        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}

        <div className="flex justify-end gap-2 pt-1">
          <Button type="submit" disabled={busy} data-testid="button-save-tax-rate">
            {busy ? "Saving…" : "Save"}
          </Button>
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
        </div>
      </form>
    </div>,
    document.body
  );
}
