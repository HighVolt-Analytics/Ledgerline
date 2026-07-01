import { useEffect } from "react";
import { createPortal } from "react-dom";
import { Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import { extractionFieldLabel } from "@/lib/documentExtractionFields";
import {
  CONFIGURABLE_VALIDATION_CHECKS,
  CUSTOM_VALIDATION_OPERATORS,
  UNIVERSAL_VALIDATION_CODE,
  customRuleSummary,
  defaultValidationRulesForProfile,
  effectiveValidationRules,
  mergeConfigurableRules,
  newCustomValidationRule,
  normalizeCustomValidationRules,
  validationCheckDescription,
  validationCheckLabel,
  validationSummary,
  type CustomValidationRule,
  type ValidationRuleConfig,
} from "@/lib/documentValidationChecks";

export { mergeConfigurableRules } from "@/lib/documentValidationChecks";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

function SeveritySelect({
  value,
  onChange,
  disabled,
}: {
  value: "block" | "warn";
  onChange: (value: "block" | "warn") => void;
  disabled?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value === "warn" ? "warn" : "block")}
      disabled={disabled}
      className="h-7 rounded-md border border-input bg-background px-2 text-[11px] disabled:opacity-50"
    >
      <option value="block">Block</option>
      <option value="warn">Warn</option>
    </select>
  );
}

function ToneBadge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "primary" | "warn";
}) {
  const classes =
    tone === "primary"
      ? "border-primary/30 bg-primary/5 text-primary"
      : tone === "warn"
        ? "border-amber-500/30 bg-amber-500/10 text-amber-800 dark:text-amber-300"
        : "border-border bg-muted/40 text-muted-foreground";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium",
        classes
      )}
    >
      {children}
    </span>
  );
}

export function ValidationDetailSection({
  docType,
}: {
  docType: DocumentTypeDefinition;
}) {
  const { standardActive, customActive } = validationSummary(docType);

  return (
    <div className="space-y-1">
      <p className="text-sm text-foreground">
        <span className="font-medium">{standardActive} standard</span>
        <span className="text-muted-foreground"> · {customActive} custom</span>
      </p>
      <p className="text-xs text-muted-foreground">Duplicate detection always on (org-wide)</p>
    </div>
  );
}

export function ValidationViewDialog({
  docType,
  onClose,
}: {
  docType: DocumentTypeDefinition;
  onClose: () => void;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopImmediatePropagation();
        onClose();
      }
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  const standardRules = effectiveValidationRules(docType);
  const customRules = normalizeCustomValidationRules(docType.customValidationRules);

  return createPortal(
    <div className="v5-dialog-root z-[210]" role="presentation">
      <button
        type="button"
        className="v5-dialog-overlay"
        aria-label="Close validation view"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="validation-view-title"
        className="v5-dialog-content max-h-[85vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 id="validation-view-title" className="text-lg font-semibold">
              Validation rules
            </h2>
            <p className="text-sm text-muted-foreground">
              {docType.code} · {docType.title}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-sm p-1 opacity-70 hover:opacity-100"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <section className="mb-5 space-y-2">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
            Always on
          </h3>
          <div className="rounded-md border border-border p-3">
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium">{validationCheckLabel(UNIVERSAL_VALIDATION_CODE)}</span>
              <ToneBadge tone="neutral">Organisation</ToneBadge>
            </div>
            <p className="mt-1 text-[11px] text-muted-foreground">
              {validationCheckDescription(UNIVERSAL_VALIDATION_CODE)}
            </p>
          </div>
        </section>

        <section className="mb-5 space-y-2">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
            Standard checks
          </h3>
          {standardRules.length === 0 ? (
            <p className="text-xs text-muted-foreground">No standard checks configured.</p>
          ) : (
            <div className="space-y-2">
              {standardRules.map((row) => (
                <div
                  key={row.code}
                  className={cn(
                    "rounded-md border p-3",
                    row.enabled ? "border-border" : "border-dashed border-border/70 opacity-60"
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium">{validationCheckLabel(row.code)}</span>
                    <div className="flex items-center gap-1.5">
                      <ToneBadge tone={row.enabled ? (row.severity === "warn" ? "warn" : "primary") : "neutral"}>
                        {row.enabled ? (row.severity === "warn" ? "Warn" : "Block") : "Off"}
                      </ToneBadge>
                    </div>
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {validationCheckDescription(row.code)}
                  </p>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="space-y-2">
          <h3 className="text-[12px] font-semibold uppercase tracking-[0.1em] text-muted-foreground">
            Custom rules
          </h3>
          {customRules.length === 0 ? (
            <p className="text-xs text-muted-foreground">No custom rules for this document type.</p>
          ) : (
            <div className="space-y-2">
              {customRules.map((row) => (
                <div
                  key={row.id}
                  className={cn(
                    "rounded-md border p-3",
                    row.enabled ? "border-border" : "border-dashed border-border/70 opacity-60"
                  )}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-sm font-medium">{row.name}</span>
                    <ToneBadge tone={row.enabled ? (row.severity === "warn" ? "warn" : "primary") : "neutral"}>
                      {row.enabled ? (row.severity === "warn" ? "Warn" : "Block") : "Off"}
                    </ToneBadge>
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">{customRuleSummary(row)}</p>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>,
    document.body
  );
}

export function ValidationChecksEditor({
  documentTypeCode,
  validationProfile,
  requiredFields = [],
  extractionFields: _extractionFields = [],
  value,
  onChange,
}: {
  documentTypeCode: string;
  validationProfile: string;
  requiredFields?: string[];
  extractionFields?: string[];
  value: ValidationRuleConfig[];
  onChange: (value: ValidationRuleConfig[]) => void;
}) {
  const rules = mergeConfigurableRules(documentTypeCode, validationProfile, value);
  const compulsory = requiredFields;

  function updateRule(code: string, patch: Partial<ValidationRuleConfig>) {
    onChange(
      rules.map((row) => (row.code === code ? { ...row, ...patch } : row))
    );
  }

  function loadProfilePreset() {
    onChange(defaultValidationRulesForProfile(validationProfile, documentTypeCode));
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          Finance checks only (tax, dates, currency, arithmetic, vendor). Compulsory field
          presence uses starred fields in Extraction fields above (VR03). Matching, bundle, and
          optional extraction run automatically from Processing playbook and Bundle rules.
          Duplicate check is always on org-wide.
        </p>
        <Button type="button" variant="outline" size="sm" onClick={loadProfilePreset}>
          Load profile preset
        </Button>
      </div>

      <div className="space-y-2 rounded-md border border-input bg-background p-3">
        {CONFIGURABLE_VALIDATION_CHECKS.map((meta) => {
          const row = rules.find((item) => item.code === meta.code) ?? {
            code: meta.code,
            enabled: false,
            severity: "block" as const,
          };
          const description = validationCheckDescription(meta.code);
          const fieldHint =
            meta.code === "VR03" && row.enabled
              ? compulsory.length
                ? compulsory.map((key) => extractionFieldLabel(key)).join(", ")
                : "No compulsory fields starred — configure in Extraction fields"
              : null;
          return (
            <div
              key={meta.code}
              className="flex flex-wrap items-start justify-between gap-2 border-b border-border/60 py-2 last:border-0"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={row.enabled}
                    onCheckedChange={(enabled) => updateRule(meta.code, { enabled })}
                    aria-label={`Toggle ${meta.label}`}
                  />
                  <div>
                    <p className="text-[11px] font-medium text-foreground">{meta.label}</p>
                    <p className="text-[10px] text-muted-foreground">{meta.group}</p>
                    {description ? (
                      <p className="mt-0.5 text-[10px] text-muted-foreground">{description}</p>
                    ) : null}
                    {fieldHint ? (
                      <p className="mt-1 text-[10px] font-medium text-foreground/80">
                        Fields: {fieldHint}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
              <SeveritySelect
                value={row.severity}
                onChange={(severity) => updateRule(meta.code, { severity })}
                disabled={!row.enabled}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function CustomValidationRulesEditor({
  value,
  onChange,
}: {
  value: CustomValidationRule[];
  onChange: (value: CustomValidationRule[]) => void;
}) {
  const rules = normalizeCustomValidationRules(value);

  function updateRule(id: string, patch: Partial<CustomValidationRule>) {
    onChange(rules.map((row) => (row.id === id ? { ...row, ...patch } : row)));
  }

  function removeRule(id: string) {
    onChange(rules.filter((row) => row.id !== id));
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] text-muted-foreground">
          Add extra field rules specific to this document type.
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onChange([...rules, newCustomValidationRule()])}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          Add rule
        </Button>
      </div>

      {rules.length === 0 ? (
        <p className="rounded-md border border-dashed border-border p-3 text-[11px] text-muted-foreground">
          No custom rules yet.
        </p>
      ) : (
        <div className="space-y-3">
          {rules.map((row) => (
            <div key={row.id} className="space-y-2 rounded-md border border-input p-3">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <Switch
                    checked={row.enabled}
                    onCheckedChange={(enabled) => updateRule(row.id, { enabled })}
                    aria-label={`Toggle ${row.name}`}
                  />
                  <Input
                    value={row.name}
                    onChange={(e) => updateRule(row.id, { name: e.target.value })}
                    className="h-8 max-w-xs text-sm"
                    placeholder="Rule name"
                  />
                </div>
                <div className="flex items-center gap-1.5">
                  <SeveritySelect
                    value={row.severity}
                    onChange={(severity) => updateRule(row.id, { severity })}
                    disabled={!row.enabled}
                  />
                  <button
                    type="button"
                    onClick={() => removeRule(row.id)}
                    className="rounded-full p-1 text-muted-foreground hover:bg-muted hover:text-destructive"
                    aria-label={`Remove ${row.name}`}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>

              <div className="grid gap-2 sm:grid-cols-3">
                <Input
                  value={row.field}
                  onChange={(e) => updateRule(row.id, { field: e.target.value })}
                  className="h-8 font-mono text-sm"
                  placeholder="field_key"
                  list="custom-validation-fields"
                />
                <select
                  value={row.operator}
                  onChange={(e) =>
                    updateRule(row.id, {
                      operator: e.target.value as CustomValidationRule["operator"],
                    })
                  }
                  className="h-8 rounded-md border border-input bg-background px-2 text-sm"
                >
                  {CUSTOM_VALIDATION_OPERATORS.map((op) => (
                    <option key={op.value} value={op.value}>
                      {op.label}
                    </option>
                  ))}
                </select>
                <Input
                  value={row.value}
                  onChange={(e) => updateRule(row.id, { value: e.target.value })}
                  className="h-8 text-sm"
                  placeholder={
                    row.operator === "present" || row.operator === "absent" ? "—" : "Value"
                  }
                  disabled={row.operator === "present" || row.operator === "absent"}
                />
              </div>
              <p className="text-[11px] text-muted-foreground">{customRuleSummary(row)}</p>
            </div>
          ))}
        </div>
      )}

      <datalist id="custom-validation-fields">
        {["vendor", "invoice_no", "total", "po_reference", "document_text", "abn", "gst"].map(
          (key) => (
            <option key={key} value={key}>
              {extractionFieldLabel(key)}
            </option>
          )
        )}
      </datalist>
    </div>
  );
}

export function ValidationRulesEditor({
  documentTypeCode,
  validationProfile,
  validationRules,
  customValidationRules,
  requiredFields,
  extractionFields,
  onChange,
}: {
  documentTypeCode: string;
  validationProfile: string;
  validationRules: ValidationRuleConfig[];
  customValidationRules: CustomValidationRule[];
  requiredFields?: string[];
  extractionFields?: string[];
  onChange: (patch: {
    validationRules?: ValidationRuleConfig[];
    customValidationRules?: CustomValidationRule[];
  }) => void;
}) {
  return (
    <div className="space-y-6">
      <ValidationChecksEditor
        documentTypeCode={documentTypeCode}
        validationProfile={validationProfile}
        requiredFields={requiredFields}
        extractionFields={extractionFields}
        value={validationRules}
        onChange={(next) => onChange({ validationRules: next })}
      />
      <CustomValidationRulesEditor
        value={customValidationRules}
        onChange={(next) => onChange({ customValidationRules: next })}
      />
    </div>
  );
}
