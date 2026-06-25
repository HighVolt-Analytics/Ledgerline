import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Layers, Pencil, Plus, Trash2, X, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ListSearchInput } from "@/components/ListSearchInput";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/cn";
import { matchesListSearch } from "@/lib/listSearch";
import { ROUTE_TARGETS } from "@/lib/v4RuleBookTypes";
import {
  DOCUMENT_TYPE_CLASSES,
  type DocumentTypeClass,
  type DocumentTypeDefinition,
  type DocumentTypeFraudRisk,
} from "@/lib/v5DocumentTypes";
import { DocumentConditionBuilder } from "@/components/rule-book/DocumentConditionBuilder";
import { DocumentTypeSamplesSection } from "@/components/rule-book/DocumentTypeSamplesSection";
import {
  buildSampleAnalysisRecord,
  markSampleAnalysisApplied,
} from "@/lib/documentTypeSampleAnalysis";
import { DocumentTypeTemplateDialog } from "@/components/rule-book/DocumentTypeTemplateDialog";
import { SimpleClassifierSection } from "@/components/rule-book/SimpleClassifierSection";
import {
  ValidationDetailSection,
  ValidationRulesEditor,
  ValidationViewDialog,
  mergeConfigurableRules,
} from "@/components/rule-book/DocumentValidationSection";
import {
  PlaybookDetailSection,
  PlaybookPolicyEditor,
} from "@/components/rule-book/DocumentPlaybookSection";
import {
  bundleMemberDetailLabel,
  documentTypeLabel,
  mergeBundleItems,
  normalizeDtCodeList,
  PURCHASE_BUNDLE_ROLE_OPTIONS,
  splitBundleItems,
  type PurchaseBundleRole,
} from "@/lib/documentBundleConfig";
import {
  EXTRACTION_FIELD_OPTIONS,
  extractionFieldLabel,
  isPresetExtractionFieldKey,
  normalizeExtractionFieldKeys,
  sanitizeExtractionFieldKey,
} from "@/lib/documentExtractionFields";
import { defaultValidationRulesForProfile } from "@/lib/documentValidationChecks";
import {
  documentTypeFromTemplate,
  inferTemplateIdFromDefinition,
} from "@/lib/documentTypeTemplates";

const CLASS_BADGE_CLASSES: Record<DocumentTypeClass, string> = {
  Transactional: "text-primary bg-primary/10 border-primary/20",
  "Pre-transactional": "text-sky-700 dark:text-sky-400 bg-sky-500/10 border-sky-500/20",
  Supporting: "text-slate-600 dark:text-slate-300 bg-slate-500/10 border-slate-500/20",
  Reconciliation: "text-violet-700 dark:text-violet-400 bg-violet-500/10 border-violet-500/20",
  Informational: "text-muted-foreground bg-muted border-border",
  "Master-data": "text-amber-700 dark:text-amber-400 bg-amber-500/10 border-amber-500/20",
  "Non-actionable": "text-muted-foreground bg-muted border-border",
  Compliance: "text-rose-700 dark:text-rose-400 bg-rose-500/10 border-rose-500/20",
};

const FRAUD_RISK_DOT: Record<DocumentTypeFraudRisk, string> = {
  low: "bg-emerald-500",
  medium: "bg-amber-500",
  high: "bg-orange-500",
  critical: "bg-destructive",
};

const POSTING_OPTIONS = ["Yes", "No", "Conditional"] as const;
const FRAUD_RISK_OPTIONS: DocumentTypeFraudRisk[] = ["low", "medium", "high", "critical"];
const KLASS_OPTIONS = DOCUMENT_TYPE_CLASSES.filter((k): k is DocumentTypeClass => k !== "all");

const TONE_CLASSES = {
  pass: "text-emerald-700 dark:text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
  fail: "text-destructive bg-destructive/10 border-destructive/20",
  skipped: "text-muted-foreground bg-muted border-border",
  warn: "text-amber-700 dark:text-amber-400 bg-amber-500/10 border-amber-500/20",
  neutral: "text-muted-foreground bg-muted border-border",
  primary: "text-primary bg-primary/10 border-primary/20",
} as const;

type Tone = keyof typeof TONE_CLASSES;

type DocumentTypesTabProps = {
  documentTypes: DocumentTypeDefinition[];
  onChange: (documentTypes: DocumentTypeDefinition[]) => void;
  onDeleteType?: (code: string) => void | Promise<void>;
  canEdit?: boolean;
};

function linesToList(value: string): string[] {
  return value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function listToLines(items: string[]): string {
  return items.join("\n");
}

function ClassBadge({ klass }: { klass: DocumentTypeClass }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none",
        CLASS_BADGE_CLASSES[klass]
      )}
    >
      {klass}
    </span>
  );
}

function ToneBadge({
  children,
  tone = "neutral",
  dot,
}: {
  children: ReactNode;
  tone?: Tone;
  dot?: boolean;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-none",
        TONE_CLASSES[tone]
      )}
    >
      {dot ? <span className="h-1.5 w-1.5 rounded-full bg-current" /> : null}
      {children}
    </span>
  );
}

function DetailCard({
  title,
  hint,
  action,
  children,
  className,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <Card className={cn("overflow-hidden", className)}>
      <div className="flex items-start justify-between gap-3 border-b border-border/60 px-4 py-3">
        <div className="min-w-0">
          <h3 className="text-sm font-medium text-foreground">{title}</h3>
          {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div className="px-4 py-3">{children}</div>
    </Card>
  );
}

function DetailFact({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="rounded-lg border border-border/70 bg-muted/25 px-3 py-2.5">
      <dt className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1 text-sm font-medium leading-snug text-foreground">{children}</dd>
    </div>
  );
}

function DetailChipList({
  items,
  emptyLabel = "None configured",
  tone = "primary",
}: {
  items: ReactNode[];
  emptyLabel?: string;
  tone?: Tone;
}) {
  if (!items.length) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, index) => (
        <ToneBadge key={index} tone={tone}>
          {item}
        </ToneBadge>
      ))}
    </div>
  );
}

function DetailSubsection({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="space-y-2">
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      {children}
    </div>
  );
}

function cardPostingTone(posting: string): Tone {
  if (posting === "Yes") return "pass";
  if (posting === "No") return "skipped";
  return "warn";
}

function FieldLabel({ children, htmlFor }: { children: ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="text-xs font-medium text-muted-foreground">
      {children}
    </label>
  );
}

function ExtractionFieldsPicker({
  id,
  value,
  onChange,
}: {
  id: string;
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const [customInput, setCustomInput] = useState("");
  const [customError, setCustomError] = useState<string | null>(null);
  const normalized = normalizeExtractionFieldKeys(value);
  const selected = new Set(normalized);
  const availablePresets = EXTRACTION_FIELD_OPTIONS.filter((row) => !selected.has(row.key));

  function removeField(key: string) {
    onChange(normalized.filter((item) => item !== key));
  }

  function addPreset(key: string) {
    if (selected.has(key)) return;
    const presetOrder = EXTRACTION_FIELD_OPTIONS.map((row) => row.key).filter(
      (item) => selected.has(item) || item === key
    );
    const customs = normalized.filter((item) => !isPresetExtractionFieldKey(item));
    onChange([...presetOrder, ...customs]);
  }

  function addCustomField() {
    const key = sanitizeExtractionFieldKey(customInput);
    if (!key) {
      setCustomError("Use lowercase letters, numbers, and underscores (e.g. contract_party).");
      return;
    }
    if (selected.has(key)) {
      setCustomError("That field is already listed.");
      return;
    }
    setCustomError(null);
    onChange([...normalized, key]);
    setCustomInput("");
  }

  return (
    <div className="space-y-3 sm:col-span-2">
      <FieldLabel htmlFor={id}>Extraction fields</FieldLabel>
      <p className="text-[11px] text-muted-foreground">
        Choose standard fields or add custom keys. These drive the invoice drawer Fields tab and OCR
        completeness checks.
      </p>

      <div className="space-y-2 rounded-md border border-input bg-background p-3">
        <p className="text-[11px] font-medium text-foreground">Selected fields</p>
        {normalized.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {normalized.map((key) => (
              <span
                key={key}
                className="inline-flex items-center gap-1 rounded-full border border-primary/30 bg-primary/5 px-2 py-0.5 text-[11px] font-medium text-primary"
              >
                <span>{extractionFieldLabel(key)}</span>
                {!isPresetExtractionFieldKey(key) ? (
                  <span className="font-mono text-[10px] text-primary/70">({key})</span>
                ) : null}
                <button
                  type="button"
                  onClick={() => removeField(key)}
                  className="rounded-full p-0.5 text-primary/70 transition-colors hover:bg-primary/10 hover:text-primary"
                  aria-label={`Remove ${extractionFieldLabel(key)}`}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        ) : (
          <p className="text-[11px] text-muted-foreground">
            No fields selected — drawer falls back to shipped defaults.
          </p>
        )}
      </div>

      <div className="space-y-2">
        <p className="text-[11px] font-medium text-foreground">Add standard field</p>
        <div
          id={id}
          className="flex flex-wrap gap-2 rounded-md border border-input bg-background p-3"
        >
          {availablePresets.length > 0 ? (
            availablePresets.map((row) => (
              <button
                key={row.key}
                type="button"
                onClick={() => addPreset(row.key)}
                className="rounded-full border border-border bg-muted/40 px-2.5 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
              >
                + {row.label}
              </button>
            ))
          ) : (
            <p className="text-[11px] text-muted-foreground">All standard fields are selected.</p>
          )}
        </div>
      </div>

      <div className="space-y-2 rounded-md border border-dashed border-border p-3">
        <FieldLabel htmlFor={`${id}-custom`}>Add custom field</FieldLabel>
        <div className="flex flex-wrap gap-2">
          <Input
            id={`${id}-custom`}
            value={customInput}
            onChange={(e) => {
              setCustomInput(e.target.value);
              setCustomError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCustomField();
              }
            }}
            placeholder="e.g. contract_party"
            className="h-9 max-w-xs font-mono text-sm"
          />
          <Button type="button" variant="outline" size="sm" onClick={addCustomField}>
            Add field
          </Button>
        </div>
        {customError ? <p className="text-[11px] text-destructive">{customError}</p> : null}
        <p className="text-[11px] text-muted-foreground">
          Custom keys use snake_case and appear in the drawer when data is captured.
        </p>
      </div>
    </div>
  );
}

function BundleDtCodePicker({
  id,
  label,
  description,
  documentTypes,
  currentCode,
  value,
  onChange,
  tone = "primary",
}: {
  id: string;
  label: string;
  description: string;
  documentTypes: DocumentTypeDefinition[];
  currentCode: string;
  value: string[];
  onChange: (value: string[]) => void;
  tone?: "primary" | "warn";
}) {
  const selected = new Set(normalizeDtCodeList(value));
  const exclude = currentCode.trim().toUpperCase();
  const options = documentTypes
    .filter((dt) => dt.code.toUpperCase() !== exclude)
    .sort((a, b) => a.code.localeCompare(b.code));

  function toggle(code: string) {
    const next = new Set(selected);
    const normalized = code.toUpperCase();
    if (next.has(normalized)) next.delete(normalized);
    else next.add(normalized);
    onChange(
      options.map((row) => row.code.toUpperCase()).filter((item) => next.has(item))
    );
  }

  const toneClasses =
    tone === "warn"
      ? {
          active: "border-amber-500 bg-amber-500/10 text-amber-800 dark:text-amber-300",
          idle: "border-border bg-muted/40 text-muted-foreground hover:border-amber-500/40",
        }
      : {
          active: "border-primary bg-primary/10 text-primary",
          idle: "border-border bg-muted/40 text-muted-foreground hover:border-primary/40",
        };

  return (
    <div className="space-y-2 sm:col-span-2">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <p className="text-[11px] text-muted-foreground">{description}</p>
      {options.length === 0 ? (
        <p className="text-xs text-muted-foreground">Add more document types to the catalogue first.</p>
      ) : (
        <div id={id} className="flex flex-wrap gap-2 rounded-md border border-input bg-background p-3">
          {options.map((row) => {
            const code = row.code.toUpperCase();
            const active = selected.has(code);
            return (
              <button
                key={code}
                type="button"
                onClick={() => toggle(code)}
                className={cn(
                  "rounded-full border px-2.5 py-1 text-left text-[11px] font-medium transition-colors",
                  active ? toneClasses.active : toneClasses.idle
                )}
                title={row.title}
              >
                {documentTypeLabel(documentTypes, code)}
              </button>
            );
          })}
        </div>
      )}
      {selected.size > 0 ? (
        <p className="text-[11px] font-mono text-muted-foreground">{Array.from(selected).join(", ")}</p>
      ) : (
        <p className="text-[11px] text-muted-foreground">None selected.</p>
      )}
    </div>
  );
}

function ListField({
  id,
  label,
  value,
  onChange,
  rows = 4,
}: {
  id: string;
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
  rows?: number;
}) {
  return (
    <div className="space-y-1.5">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <textarea
        id={id}
        rows={rows}
        value={listToLines(value)}
        onChange={(e) => onChange(linesToList(e.target.value))}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        placeholder="One item per line"
      />
    </div>
  );
}

function useDialogLock() {
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);
}

function DocumentTypeDetailDialog({
  docType,
  documentTypes,
  canEdit,
  validationViewOpen,
  onClose,
  onEdit,
  onDelete,
  onViewValidation,
}: {
  docType: DocumentTypeDefinition;
  documentTypes: DocumentTypeDefinition[];
  canEdit: boolean;
  validationViewOpen: boolean;
  onClose: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onViewValidation: () => void;
}) {
  useDialogLock();
  const conditionalBundle = splitBundleItems(docType.bundleConditional);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !validationViewOpen) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, validationViewOpen]);

  return createPortal(
    <div className="v5-dialog-root" role="presentation">
      <button
        type="button"
        className="v5-dialog-overlay"
        aria-label="Close document type details"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="document-type-detail-title"
        className="v5-dialog-content document-type-detail-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="detail-dialog-header">
          <div className="flex items-start justify-between gap-4 pr-2">
            <div className="min-w-0 space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="inline-flex rounded-md border border-border bg-muted/50 px-2 py-0.5 font-mono text-xs font-semibold text-foreground">
                  {docType.code}
                </span>
                <ClassBadge klass={docType.klass} />
                {!docType.enabled ? <ToneBadge tone="fail">Disabled</ToneBadge> : null}
              </div>
              <h2
                id="document-type-detail-title"
                className="text-lg font-semibold leading-tight tracking-tight text-foreground"
              >
                {docType.title}
              </h2>
              <p className="text-sm leading-relaxed text-muted-foreground">{docType.oneLine}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              {canEdit ? (
                <>
                  <Button type="button" size="sm" variant="outline" className="h-8" onClick={onEdit}>
                    <Pencil className="h-3.5 w-3.5 mr-1" />
                    Edit
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="ghost"
                    className="h-8 text-destructive hover:text-destructive"
                    onClick={onDelete}
                    aria-label={`Delete ${docType.code}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </>
              ) : null}
              <button
                type="button"
                onClick={onClose}
                className="rounded-sm p-1 opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          </div>

          <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <DetailFact label="Workspace">
              {docType.routeTarget}
            </DetailFact>
            <DetailFact label="Posting">{docType.posting}</DetailFact>
            <DetailFact label="Fraud risk">
              <span className="inline-flex items-center gap-1.5 capitalize">
                <span
                  className={cn("h-2 w-2 rounded-full", FRAUD_RISK_DOT[docType.fraudRisk])}
                  aria-hidden
                />
                {docType.fraudRisk}
              </span>
            </DetailFact>
            <DetailFact label="Classifier">
              {docType.classifier.enabled
                ? `On · priority ${docType.classifier.priority}`
                : "Off"}
            </DetailFact>
          </dl>
        </div>

        <div className="detail-dialog-body">
          <DetailCard
            title="Bundle rules"
            hint="Required and recommended documents on the same PO reference"
          >
            <div className="space-y-4">
              <DetailSubsection label="Required before posting">
                <DetailChipList
                  items={docType.bundleMandatory.map((code) =>
                    bundleMemberDetailLabel(code, documentTypes)
                  )}
                  emptyLabel="No required bundle members"
                />
              </DetailSubsection>
              {conditionalBundle.dtCodes.length || conditionalBundle.advisories.length ? (
                <DetailSubsection label="Recommended (advisory)">
                  <div className="space-y-3">
                    {conditionalBundle.dtCodes.length ? (
                      <DetailChipList
                        tone="warn"
                        items={conditionalBundle.dtCodes.map((code) =>
                          documentTypeLabel(documentTypes, code)
                        )}
                        emptyLabel=""
                      />
                    ) : null}
                    {conditionalBundle.advisories.length ? (
                      <ul className="space-y-1 text-sm text-foreground">
                        {conditionalBundle.advisories.map((item, index) => (
                          <li key={index} className="flex gap-2 text-muted-foreground">
                            <span className="text-primary/40">·</span>
                            <span>{item}</span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                </DetailSubsection>
              ) : (
                <DetailSubsection label="Recommended (advisory)">
                  <p className="text-sm text-muted-foreground">None configured</p>
                </DetailSubsection>
              )}
            </div>
          </DetailCard>

          <div className="grid gap-3 sm:grid-cols-2">
            <DetailCard title="Processing playbook" hint="Match and approval preset">
              <PlaybookDetailSection docType={docType} />
            </DetailCard>
            <DetailCard
              title="Validation"
              hint="Standard, custom, and duplicate checks"
              action={
                <Button type="button" variant="outline" size="sm" className="h-8" onClick={onViewValidation}>
                  <Eye className="mr-1.5 h-3.5 w-3.5" />
                  View
                </Button>
              }
            >
              <ValidationDetailSection docType={docType} />
            </DetailCard>
          </div>

          <DetailCard title="Extraction fields" hint="Shown in invoice drawer → Fields tab">
            <DetailChipList
              items={docType.extractionFields.map((key) => extractionFieldLabel(key))}
              emptyLabel="No fields configured — drawer uses defaults"
            />
          </DetailCard>
        </div>
      </div>
    </div>,
    document.body
  );
}

function DocumentTypeEditDialog({
  draft,
  documentTypes,
  existingCodes,
  isNew,
  onChange,
  onClose,
  onSave,
}: {
  draft: DocumentTypeDefinition;
  documentTypes: DocumentTypeDefinition[];
  existingCodes: Set<string>;
  isNew: boolean;
  onChange: (next: DocumentTypeDefinition) => void;
  onClose: () => void;
  onSave: () => void;
}) {
  useDialogLock();
  const conditionalBundle = splitBundleItems(draft.bundleConditional);
  const templateId = useMemo(
    () => inferTemplateIdFromDefinition(draft),
    [draft]
  );
  const advancedMode = Boolean(draft.classifierCustomized);

  function patchClassifier(
    classifier: Partial<DocumentTypeDefinition["classifier"]>
  ): DocumentTypeDefinition {
    return {
      ...draft,
      classifierCustomized: true,
      classifier: { ...draft.classifier, ...classifier },
    };
  }

  function useSimpleMode() {
    onChange({
      ...draft,
      classifierCustomized: false,
    });
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const codeTaken = existingCodes.has(draft.code.trim().toUpperCase());
  const selectClass =
    "h-9 w-full rounded-md border border-input bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

  return createPortal(
    <div className="v5-dialog-root" role="presentation">
      <button
        type="button"
        className="v5-dialog-overlay"
        aria-label="Close editor"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="document-type-edit-title"
        className="v5-dialog-content document-type-edit-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="detail-dialog-header">
          <div className="flex items-start justify-between gap-4 pr-1">
            <div className="min-w-0 space-y-1">
              <div className="flex flex-wrap items-center gap-2">
                {!isNew ? (
                  <span className="inline-flex rounded-md border border-border bg-muted/50 px-2 py-0.5 font-mono text-xs font-semibold text-foreground">
                    {draft.code}
                  </span>
                ) : null}
                <h2 id="document-type-edit-title" className="text-lg font-semibold tracking-tight">
                  {isNew ? "New document type" : "Edit document type"}
                </h2>
              </div>
              <p className="text-sm text-muted-foreground">
                {isNew
                  ? "Name the type and confirm how we recognise it. Advanced options are optional."
                  : "Update labels, recognition signals, extraction, and processing rules."}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="shrink-0 rounded-sm p-1 opacity-70 ring-offset-background transition-opacity hover:opacity-100 focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2"
              aria-label="Close"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="detail-dialog-body">
          <DetailCard title="Identity" hint="Code, labels, routing, and enablement">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <FieldLabel htmlFor="dt-code">Code</FieldLabel>
                <Input
                  id="dt-code"
                  value={draft.code}
                  onChange={(e) => onChange({ ...draft, code: e.target.value.toUpperCase() })}
                  className="h-9 font-mono text-sm"
                />
                {codeTaken ? (
                  <p className="text-xs text-destructive">That code is already in use.</p>
                ) : null}
              </div>
              <div className="space-y-1.5">
                <FieldLabel htmlFor="dt-short">Short title</FieldLabel>
                <Input
                  id="dt-short"
                  value={draft.shortTitle}
                  onChange={(e) => onChange({ ...draft, shortTitle: e.target.value })}
                  className="h-9 text-sm"
                />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <FieldLabel htmlFor="dt-title">Title</FieldLabel>
                <Input
                  id="dt-title"
                  value={draft.title}
                  onChange={(e) => onChange({ ...draft, title: e.target.value })}
                  className="h-9 text-sm"
                />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <FieldLabel htmlFor="dt-oneline">Summary</FieldLabel>
                <textarea
                  id="dt-oneline"
                  rows={2}
                  value={draft.oneLine}
                  onChange={(e) => onChange({ ...draft, oneLine: e.target.value })}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
              </div>
              <div className="space-y-1.5">
                <FieldLabel htmlFor="dt-klass">Class</FieldLabel>
                <select
                  id="dt-klass"
                  value={draft.klass}
                  onChange={(e) =>
                    onChange({ ...draft, klass: e.target.value as DocumentTypeClass })
                  }
                  className={selectClass}
                >
                  {KLASS_OPTIONS.map((klass) => (
                    <option key={klass} value={klass}>
                      {klass}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <FieldLabel htmlFor="dt-posting">Posting</FieldLabel>
                <select
                  id="dt-posting"
                  value={draft.posting}
                  onChange={(e) => onChange({ ...draft, posting: e.target.value })}
                  className={selectClass}
                >
                  {POSTING_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <FieldLabel htmlFor="dt-fraud">Fraud risk</FieldLabel>
                <select
                  id="dt-fraud"
                  value={draft.fraudRisk}
                  onChange={(e) =>
                    onChange({ ...draft, fraudRisk: e.target.value as DocumentTypeFraudRisk })
                  }
                  className={cn(selectClass, "capitalize")}
                >
                  {FRAUD_RISK_OPTIONS.map((risk) => (
                    <option key={risk} value={risk}>
                      {risk}
                    </option>
                  ))}
                </select>
              </div>
              <div className="space-y-1.5">
                <FieldLabel htmlFor="dt-route">Workspace route</FieldLabel>
                <select
                  id="dt-route"
                  value={draft.routeTarget}
                  onChange={(e) => onChange({ ...draft, routeTarget: e.target.value })}
                  className={selectClass}
                >
                  {ROUTE_TARGETS.map((route) => (
                    <option key={route} value={route}>
                      {route}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2 sm:col-span-2">
                <Switch
                  id="dt-enabled"
                  checked={draft.enabled}
                  onCheckedChange={(enabled) => onChange({ ...draft, enabled })}
                />
                <FieldLabel htmlFor="dt-enabled">Enabled for classification and routing</FieldLabel>
              </div>
            </div>
          </DetailCard>

          <DetailCard
            title="Sample files"
            hint={
              draft.sampleAnalysis
                ? "Sample analysis on record — upload new files to re-analyze"
                : "Detect recognition signals and extraction fields from examples"
            }
          >
            <DocumentTypeSamplesSection
              draft={draft}
              templateId={templateId}
              sampleAnalysis={draft.sampleAnalysis}
              onRecordAnalysis={(sampleAnalysis) => onChange({ ...draft, sampleAnalysis })}
              onApply={(next, proposal, filenames) => {
                onChange({
                  ...next,
                  sampleAnalysis: markSampleAnalysisApplied(
                    buildSampleAnalysisRecord(filenames, proposal, { afterApply: true })
                  ),
                });
              }}
            />
          </DetailCard>

          <DetailCard
            title="Recognition"
            hint={
              advancedMode
                ? "Advanced condition tree — for power users"
                : "How we identify this document after OCR"
            }
          >
            {advancedMode ? (
              <div className="space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    Editing raw AND/OR conditions. Switch back to simple mode when finished.
                  </p>
                  <Button type="button" size="sm" variant="outline" className="h-8" onClick={useSimpleMode}>
                    Use simple recognition
                  </Button>
                </div>
                <div className="flex items-center gap-2">
                  <Switch
                    id="dt-classifier-enabled"
                    checked={draft.classifier.enabled}
                    onCheckedChange={(enabled) => onChange(patchClassifier({ enabled }))}
                  />
                  <FieldLabel htmlFor="dt-classifier-enabled">
                    Use classifier rules for this type
                  </FieldLabel>
                </div>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <FieldLabel htmlFor="dt-classifier-priority">Priority (tie-breaker)</FieldLabel>
                    <Input
                      id="dt-classifier-priority"
                      type="number"
                      min={1}
                      value={draft.classifier.priority}
                      onChange={(e) =>
                        onChange(patchClassifier({ priority: Number(e.target.value) || 100 }))
                      }
                      className="h-9 text-sm"
                      disabled={!draft.classifier.enabled}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <FieldLabel htmlFor="dt-classifier-confidence">Rule strength hint</FieldLabel>
                    <Input
                      id="dt-classifier-confidence"
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      value={draft.classifier.confidence}
                      onChange={(e) =>
                        onChange(
                          patchClassifier({
                            confidence: Math.min(1, Math.max(0, Number(e.target.value) || 0)),
                          })
                        )
                      }
                      className="h-9 text-sm"
                      disabled={!draft.classifier.enabled}
                    />
                  </div>
                </div>
                {draft.classifier.enabled ? (
                  <DocumentConditionBuilder
                    root={draft.classifier.root}
                    onChange={(root) => onChange(patchClassifier({ root }))}
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Built-in heuristics apply when the classifier is off.
                  </p>
                )}
              </div>
            ) : (
              <SimpleClassifierSection
                draft={draft}
                templateId={templateId}
                onChange={onChange}
                onOpenAdvanced={() => onChange({ ...draft, classifierCustomized: true })}
              />
            )}
          </DetailCard>

          <DetailCard title="Evidence & routing" hint="Fields and confidence used after classification">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5 sm:col-span-2">
                <FieldLabel htmlFor="dt-absent-fields">Must be absent</FieldLabel>
                <Input
                  id="dt-absent-fields"
                  value={draft.absentFields.join(", ")}
                  onChange={(e) =>
                    onChange({
                      ...draft,
                      absentFields: e.target.value
                        .split(",")
                        .map((part) => part.trim())
                        .filter(Boolean),
                    })
                  }
                  placeholder="invoice_no"
                  className="h-9 text-sm font-mono"
                />
              </div>
              {advancedMode ? (
                <div className="space-y-1.5">
                  <FieldLabel htmlFor="dt-min-route-confidence">Min route confidence</FieldLabel>
                  <Input
                    id="dt-min-route-confidence"
                    type="number"
                    min={0}
                    max={1}
                    step={0.01}
                    value={draft.minRouteConfidence}
                    onChange={(e) =>
                      onChange({
                        ...draft,
                        minRouteConfidence: Math.min(1, Math.max(0, Number(e.target.value) || 0)),
                      })
                    }
                    className="h-9 text-sm"
                  />
                </div>
              ) : null}
              <div className="space-y-1.5">
                <FieldLabel htmlFor="dt-validation-profile">Validation profile</FieldLabel>
                <select
                  id="dt-validation-profile"
                  value={draft.validationProfile}
                  onChange={(e) => onChange({ ...draft, validationProfile: e.target.value })}
                  className={selectClass}
                >
                  <option value="">Standard (default for code)</option>
                  <option value="standard">Standard — full AU invoice checks</option>
                  <option value="direct_expense">Direct expense — foreign / non-PO SaaS</option>
                  <option value="non_actionable">Non-actionable — vault reference docs</option>
                </select>
              </div>
            </div>
          </DetailCard>

          <DetailCard title="Processing playbook" hint="Match and approval preset">
            <PlaybookPolicyEditor draft={draft} onChange={onChange} />
          </DetailCard>

          <DetailCard title="Validation" hint="Standard checks and custom field rules">
            <ValidationRulesEditor
              documentTypeCode={draft.code}
              validationProfile={draft.validationProfile}
              validationRules={draft.validationRules}
              customValidationRules={draft.customValidationRules}
              onChange={(patch) => onChange({ ...draft, ...patch })}
            />
          </DetailCard>

          <DetailCard title="Extraction fields" hint="Parsed fields shown in invoice drawer → Fields tab">
            <ExtractionFieldsPicker
              id="dt-extraction-fields"
              value={draft.extractionFields}
              onChange={(extractionFields) => onChange({ ...draft, extractionFields })}
            />
          </DetailCard>

          <DetailCard
            title="Bundle rules"
            hint="Required and recommended documents on the same PO reference"
          >
            <div className="space-y-5">
              <div className="space-y-1.5">
                <FieldLabel htmlFor="dt-purchase-bundle-role">Purchase bundle link</FieldLabel>
                <p className="text-xs text-muted-foreground">
                  How this type is verified on the PO when it is a bundle member.
                </p>
                <select
                  id="dt-purchase-bundle-role"
                  value={draft.purchaseBundleRole}
                  onChange={(e) =>
                    onChange({
                      ...draft,
                      purchaseBundleRole: e.target.value as PurchaseBundleRole,
                    })
                  }
                  className={selectClass}
                >
                  {PURCHASE_BUNDLE_ROLE_OPTIONS.map((row) => (
                    <option key={row.value || "none"} value={row.value}>
                      {row.label}
                    </option>
                  ))}
                </select>
              </div>
              <DetailSubsection label="Required before posting">
                <BundleDtCodePicker
                  id="dt-bundle-mandatory"
                  label="Required types"
                  description="Blocks posting until each selected type is on the PO."
                  documentTypes={documentTypes}
                  currentCode={draft.code}
                  value={draft.bundleMandatory}
                  onChange={(bundleMandatory) => onChange({ ...draft, bundleMandatory })}
                />
              </DetailSubsection>
              <DetailSubsection label="Recommended (advisory)">
                <BundleDtCodePicker
                  id="dt-bundle-conditional"
                  label="Companion types"
                  description="Flagged when missing but do not block posting."
                  documentTypes={documentTypes}
                  currentCode={draft.code}
                  value={conditionalBundle.dtCodes}
                  tone="warn"
                  onChange={(dtCodes) =>
                    onChange({
                      ...draft,
                      bundleConditional: mergeBundleItems(dtCodes, conditionalBundle.advisories),
                    })
                  }
                />
                <ListField
                  id="dt-bundle-conditional-notes"
                  label="Advisory notes"
                  value={conditionalBundle.advisories}
                  onChange={(advisories) =>
                    onChange({
                      ...draft,
                      bundleConditional: mergeBundleItems(conditionalBundle.dtCodes, advisories),
                    })
                  }
                  rows={3}
                />
              </DetailSubsection>
            </div>
          </DetailCard>
        </div>

        <div className="detail-dialog-footer">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onSave}
            disabled={!draft.code.trim() || !draft.title.trim() || codeTaken}
          >
            {isNew ? "Create type" : "Save changes"}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}

export function DocumentTypesTab({
  documentTypes,
  onChange,
  onDeleteType,
  canEdit = false,
}: DocumentTypesTabProps) {
  const [classFilter, setClassFilter] = useState<"all" | DocumentTypeClass>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCode, setSelectedCode] = useState<string | null>(null);
  const [validationViewCode, setValidationViewCode] = useState<string | null>(null);
  const [editing, setEditing] = useState<DocumentTypeDefinition | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [templateDialogOpen, setTemplateDialogOpen] = useState(false);

  const filtered = useMemo(
    () =>
      (classFilter === "all"
        ? documentTypes
        : documentTypes.filter((dt) => dt.klass === classFilter)
      ).filter((docType) =>
        matchesListSearch(
          searchQuery,
          docType.code,
          docType.title,
          docType.shortTitle,
          docType.oneLine,
          docType.klass,
          docType.routeTarget
        )
      ),
    [classFilter, documentTypes, searchQuery]
  );

  const selected = useMemo(
    () => documentTypes.find((dt) => dt.code === selectedCode) ?? null,
    [documentTypes, selectedCode]
  );

  const validationViewDoc = useMemo(
    () => documentTypes.find((dt) => dt.code === validationViewCode) ?? null,
    [documentTypes, validationViewCode]
  );

  const removeType = async (code: string) => {
    const target = documentTypes.find(
      (dt) => dt.code.trim().toUpperCase() === code.trim().toUpperCase()
    );
    const label = target ? `${target.code} · ${target.title}` : code;
    const message = `Do you want to delete this document type?\n\n${label}`;
    const confirmed = window.confirm(message);
    if (!confirmed) return;

    setSelectedCode(null);
    setValidationViewCode((current) =>
      current?.trim().toUpperCase() === code.trim().toUpperCase() ? null : current
    );
    if (editing?.code.trim().toUpperCase() === code.trim().toUpperCase()) {
      setEditing(null);
      setIsNew(false);
    }

    if (onDeleteType) {
      onDeleteType(code);
      return;
    }

    onChange(
      documentTypes.filter(
        (dt) => dt.code.trim().toUpperCase() !== code.trim().toUpperCase()
      )
    );
  };

  const saveEdit = () => {
    if (!editing) return;
    const normalized = editing.code.trim().toUpperCase();
    const validationRules = mergeConfigurableRules(
      normalized,
      editing.validationProfile,
      editing.validationRules
    );
    const next = { ...editing, code: normalized, validationRules };
    if (isNew) {
      const duplicate = documentTypes.some(
        (dt) => dt.code.trim().toUpperCase() === normalized
      );
      if (duplicate) return;
      onChange([...documentTypes, next]);
    } else {
      onChange(
        documentTypes.map((dt) => (dt.code === selectedCode ? next : dt))
      );
      if (selectedCode !== normalized) {
        setSelectedCode(normalized);
      }
    }
    setEditing(null);
    setIsNew(false);
  };

  const existingCodesForEdit = useMemo(() => {
    const codes = new Set(
      documentTypes
        .filter((dt) => (isNew ? true : dt.code !== selectedCode))
        .map((dt) => dt.code.trim().toUpperCase())
    );
    return codes;
  }, [documentTypes, isNew, selectedCode]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-sm text-muted-foreground max-w-2xl">
          Add a type by uploading sample files (recommended) or from a template. Recognition
          rules drive routing; GL accounts are set under Purchase, Expenses, and Team tabs.
        </p>
        {canEdit ? (
          <Button
            type="button"
            size="sm"
            onClick={() => setTemplateDialogOpen(true)}
            data-testid="button-add-document-type"
          >
            <Plus className="h-3.5 w-3.5 mr-1" />
            Add type
          </Button>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {DOCUMENT_TYPE_CLASSES.map((klass) => (
          <button
            key={klass}
            type="button"
            onClick={() => setClassFilter(klass)}
            data-testid={`filter-class-${klass}`}
            className={cn(
              "rounded-full border px-3 py-1 text-xs font-medium transition",
              classFilter === klass
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:bg-muted"
            )}
          >
            {klass === "all" ? "All classes" : klass}
          </button>
        ))}
        <ListSearchInput
          value={searchQuery}
          onChange={setSearchQuery}
          placeholder="Search types…"
          testId="input-document-types-search"
          className="ml-auto"
        />
      </div>

      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border bg-card/50 px-6 py-16 text-center">
          <div className="mb-3 text-muted-foreground/50">
            <Layers className="h-8 w-8" />
          </div>
          <h3 className="text-sm font-semibold text-foreground">
            {searchQuery.trim() ? "No types match your search" : "No types in this class"}
          </h3>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {filtered.map((docType) => (
            <button
              key={docType.code}
              type="button"
              onClick={() => setSelectedCode(docType.code)}
              data-testid={`card-dt-${docType.code}`}
              className={cn(
                "group flex flex-col rounded-xl border border-border bg-card p-4 text-left transition hover:-translate-y-px hover:shadow-sm",
                !docType.enabled && "opacity-60"
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-foreground">{docType.code}</span>
                <span
                  className={cn("h-2 w-2 rounded-full", FRAUD_RISK_DOT[docType.fraudRisk])}
                  title={`Fraud risk: ${docType.fraudRisk}`}
                />
              </div>
              <div className="mt-1 text-sm font-medium text-foreground">{docType.shortTitle}</div>
              <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                {docType.oneLine}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <ClassBadge klass={docType.klass} />
                <ToneBadge tone={cardPostingTone(docType.posting)}>
                  Post: {docType.posting}
                </ToneBadge>
                {docType.sampleAnalysis ? (
                  <ToneBadge tone="primary">Samples analyzed</ToneBadge>
                ) : null}
                {!docType.enabled ? <ToneBadge tone="fail">Off</ToneBadge> : null}
              </div>
            </button>
          ))}
        </div>
      )}

      {selected && !editing ? (
        <DocumentTypeDetailDialog
          docType={selected}
          documentTypes={documentTypes}
          canEdit={canEdit}
          validationViewOpen={validationViewCode === selected.code}
          onClose={() => setSelectedCode(null)}
          onViewValidation={() => setValidationViewCode(selected.code)}
          onEdit={() => {
            setIsNew(false);
            setEditing({ ...selected });
          }}
          onDelete={() => removeType(selected.code)}
        />
      ) : null}

      {validationViewDoc ? (
        <ValidationViewDialog
          docType={validationViewDoc}
          onClose={() => setValidationViewCode(null)}
        />
      ) : null}

      {editing ? (
        <DocumentTypeEditDialog
          draft={editing}
          documentTypes={documentTypes}
          existingCodes={existingCodesForEdit}
          isNew={isNew}
          onChange={setEditing}
          onClose={() => {
            setEditing(null);
            setIsNew(false);
          }}
          onSave={saveEdit}
        />
      ) : null}

      <DocumentTypeTemplateDialog
        open={templateDialogOpen}
        onClose={() => setTemplateDialogOpen(false)}
        onSelect={(templateId) => {
          setTemplateDialogOpen(false);
          setIsNew(true);
          setEditing(documentTypeFromTemplate(templateId, documentTypes));
          setSelectedCode(null);
        }}
      />
    </div>
  );
}
