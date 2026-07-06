import { useEffect, useMemo, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Layers, Pencil, Plus, Star, Trash2, X, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ListSearchInput } from "@/components/ListSearchInput";
import { cn } from "@/lib/cn";
import { matchesListSearch } from "@/lib/listSearch";
import { ROUTE_TARGETS } from "@/lib/v4RuleBookTypes";
import {
  DOCUMENT_TYPE_CLASSES,
  type DocumentTypeClass,
  type DocumentTypeDefinition,
} from "@/lib/v5DocumentTypes";
import { derivePostingFromKlassAndProfile } from "@/lib/documentTypeKlass";
import { applyRoutePlaybookDefaults } from "@/lib/documentPlaybookConfig";
import { DocumentTypeTemplateDialog } from "@/components/rule-book/DocumentTypeTemplateDialog";
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
  BundleRulesDetailSection,
  BundleRulesEditor,
} from "@/components/rule-book/BundleRulesEditor";
import {
  EXTRACTION_FIELD_OPTIONS,
  extractionFieldKeyError,
  extractionFieldLabel,
  formatExtractionFieldKeyInput,
  isPresetExtractionFieldKey,
  normalizeExtractionFieldKeys,
  sanitizeExtractionFieldKey,
} from "@/lib/documentExtractionFields";
import {
  ensureExtractionSuperset,
  normalizeCompulsoryFields,
  optionalExtractionFields,
} from "@/lib/documentCompulsoryFields";
import {
  documentTypeFromTemplate,
} from "@/lib/documentTypeTemplates";
import { bundleConfigWarnings } from "@/lib/documentTypeBundleValidation";
import { normalizeBundleConditional } from "@/lib/documentBundleConfig";
import { DocumentRecognitionEditor } from "@/components/rule-book/DocumentRecognitionEditor";
import { documentTypeReadiness } from "@/lib/documentMatchRules";
import { recognitionSummary } from "@/lib/documentTypeRecognition";
import {
  DocumentTypePostToDetail,
  DocumentTypePostToEditor,
} from "@/components/rule-book/DocumentTypePostToSection";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";
import { postToMissingOnCard } from "@/lib/documentTypePostToValidation";
const CLASS_BADGE_CLASSES: Record<DocumentTypeClass, string> = {
  Transactional: "text-primary bg-primary/10 border-primary/20",
  "Non-transactional": "text-slate-600 dark:text-slate-300 bg-slate-500/10 border-slate-500/20",
};

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

function cardPostingTone(posting: string): Tone {
  if (posting === "Yes") return "pass";
  if (posting === "No") return "skipped";
  return "warn";
}

function derivedPostingForDraft(draft: DocumentTypeDefinition): string {
  return derivePostingFromKlassAndProfile(draft.klass, draft.playbookProfile, draft.posting);
}

function applyDraftChange(
  draft: DocumentTypeDefinition,
  patch: Partial<DocumentTypeDefinition>
): DocumentTypeDefinition {
  const next = { ...draft, ...patch };
  const posting = derivePostingFromKlassAndProfile(
    next.klass,
    next.playbookProfile,
    next.posting
  );
  return { ...next, posting };
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
  extractionFields,
  requiredFields,
  onChange,
}: {
  id: string;
  extractionFields: string[];
  requiredFields: string[];
  onChange: (next: { extractionFields: string[]; requiredFields: string[] }) => void;
}) {
  const [customInput, setCustomInput] = useState("");
  const [customError, setCustomError] = useState<string | null>(null);
  const normalized = normalizeExtractionFieldKeys(extractionFields);
  const compulsory = new Set(normalizeCompulsoryFields(requiredFields, normalized));
  const selected = new Set(normalized);
  const availablePresets = EXTRACTION_FIELD_OPTIONS.filter((row) => !selected.has(row.key));

  function emit(extraction: string[], required: string[]) {
    const extractionNorm = normalizeExtractionFieldKeys(extraction);
    const requiredNorm = normalizeCompulsoryFields(required, extractionNorm);
    onChange({
      extractionFields: ensureExtractionSuperset(requiredNorm, extractionNorm),
      requiredFields: requiredNorm,
    });
  }

  function removeField(key: string) {
    emit(
      normalized.filter((item) => item !== key),
      [...compulsory].filter((item) => item !== key)
    );
  }

  function toggleCompulsory(key: string) {
    const nextRequired = compulsory.has(key)
      ? [...compulsory].filter((item) => item !== key)
      : [...compulsory, key];
    emit(normalized, nextRequired);
  }

  function addPreset(key: string) {
    if (selected.has(key)) return;
    const presetOrder = EXTRACTION_FIELD_OPTIONS.map((row) => row.key).filter(
      (item) => selected.has(item) || item === key
    );
    const customs = normalized.filter((item) => !isPresetExtractionFieldKey(item));
    emit([...presetOrder, ...customs], [...compulsory]);
  }

  function addCustomField() {
    const validationError = extractionFieldKeyError(customInput);
    if (validationError) {
      setCustomError(validationError);
      return;
    }
    const key = sanitizeExtractionFieldKey(customInput);
    if (!key) {
      setCustomError(extractionFieldKeyError(customInput) ?? "Invalid field name.");
      return;
    }
    if (selected.has(key)) {
      setCustomError("That field is already listed.");
      return;
    }
    setCustomError(null);
    emit([...normalized, key], [...compulsory]);
    setCustomInput("");
  }

  return (
    <div className="space-y-3 sm:col-span-2">
      <FieldLabel htmlFor={id}>Extraction fields</FieldLabel>
      <p className="text-[11px] text-muted-foreground">
        Choose fields to extract and show in the invoice drawer. Starred fields are{" "}
        <span className="font-medium text-foreground">compulsory</span> — they drive VR03,
        playbook blocking, and Approve. Unstarred fields are optional (warn-only if missing).
      </p>

      <div className="space-y-2 rounded-md border border-input bg-background p-3">
        <p className="text-[11px] font-medium text-foreground">Selected fields</p>
        {normalized.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {normalized.map((key) => {
              const isCompulsory = compulsory.has(key);
              return (
                <span
                  key={key}
                  className={cn(
                    "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
                    isCompulsory
                      ? "border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-100"
                      : "border-primary/30 bg-primary/5 text-primary"
                  )}
                >
                  <button
                    type="button"
                    onClick={() => toggleCompulsory(key)}
                    className={cn(
                      "rounded-full p-0.5 transition-colors",
                      isCompulsory
                        ? "text-amber-700 hover:bg-amber-500/20 dark:text-amber-200"
                        : "text-primary/50 hover:bg-primary/10 hover:text-primary"
                    )}
                    aria-label={
                      isCompulsory
                        ? `Mark ${extractionFieldLabel(key)} as optional`
                        : `Mark ${extractionFieldLabel(key)} as compulsory`
                    }
                    title={isCompulsory ? "Compulsory" : "Optional — click to require"}
                  >
                    <Star className={cn("h-3 w-3", isCompulsory && "fill-current")} />
                  </button>
                  <span>{extractionFieldLabel(key)}</span>
                  {!isPresetExtractionFieldKey(key) ? (
                    <span className="font-mono text-[10px] opacity-70">({key})</span>
                  ) : null}
                  <button
                    type="button"
                    onClick={() => removeField(key)}
                    className="rounded-full p-0.5 opacity-70 transition-colors hover:bg-black/5 hover:opacity-100"
                    aria-label={`Remove ${extractionFieldLabel(key)}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              );
            })}
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
              setCustomInput(formatExtractionFieldKeyInput(e.target.value));
              setCustomError(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addCustomField();
              }
            }}
            placeholder="e.g. contract_party"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck={false}
            className="h-9 max-w-xs font-mono text-sm"
          />
          <Button type="button" variant="outline" size="sm" onClick={addCustomField}>
            Add field
          </Button>
        </div>
        {customError ? <p className="text-[11px] text-destructive">{customError}</p> : null}
        {customInput && !customError ? (
          <p className="text-[11px] text-muted-foreground">
            Will save as: <span className="font-mono">{customInput}</span>
          </p>
        ) : null}
        <p className="text-[11px] text-muted-foreground">
          Custom keys use snake_case and appear in the drawer when data is captured.
        </p>
      </div>
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
  coaAccounts,
  onClose,
  onEdit,
  onDelete,
  onViewValidation,
}: {
  docType: DocumentTypeDefinition;
  documentTypes: DocumentTypeDefinition[];
  canEdit: boolean;
  validationViewOpen: boolean;
  coaAccounts: import("@/api/types").ChartOfAccountRow[];
  onClose: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onViewValidation: () => void;
}) {
  useDialogLock();

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
              <p className="text-sm leading-relaxed text-muted-foreground">
                {recognitionSummary(docType)}
              </p>
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

          <dl className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-3">
            <DetailFact label="Class">{docType.klass}</DetailFact>
            <DetailFact label="Posting">{docType.posting}</DetailFact>
            <DetailFact label="Workspace">{docType.routeTarget}</DetailFact>
          </dl>
        </div>

        <div className="detail-dialog-body">
          <DetailCard
            title="Supporting document requirements"
            hint="Dossier members on the same PO or SO"
          >
            <BundleRulesDetailSection docType={docType} documentTypes={documentTypes} />
          </DetailCard>

          <div className="grid gap-3 sm:grid-cols-2">
            <DetailCard title="Processing playbook" hint="Match and approval preset">
              <PlaybookDetailSection docType={docType} />
            </DetailCard>
            <DetailCard title="Post to" hint="GL account from chart of accounts">
              <DocumentTypePostToDetail docType={docType} accounts={coaAccounts} />
            </DetailCard>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
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
            <div className="space-y-3">
              <div>
                <p className="text-[11px] font-medium text-foreground">Compulsory</p>
                <DetailChipList
                  items={docType.requiredFields.map((key) => extractionFieldLabel(key))}
                  emptyLabel="None — approve falls back to vendor, total, due date"
                />
              </div>
              <div>
                <p className="text-[11px] font-medium text-foreground">Optional extract</p>
                <DetailChipList
                  items={optionalExtractionFields(
                    docType.extractionFields,
                    docType.requiredFields
                  ).map((key) => extractionFieldLabel(key))}
                  emptyLabel="No optional fields"
                />
              </div>
              {docType.absentFields.length > 0 ? (
                <div>
                  <p className="text-[11px] font-medium text-foreground">Must not appear</p>
                  <DetailChipList
                    items={docType.absentFields.map((key) => extractionFieldLabel(key))}
                    emptyLabel="None"
                  />
                </div>
              ) : null}
            </div>
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
  const [showAdvancedIdentity, setShowAdvancedIdentity] = useState(!isNew);
  const { data: coaAccounts = [] } = useChartOfAccounts();

  const readiness = useMemo(
    () =>
      documentTypeReadiness(
        {
          title: draft.title,
          recognitionMode: draft.recognitionMode,
          recognitionSignals: draft.recognitionSignals,
          llmPrompt: draft.llmPrompt,
          code: draft.code,
          posting: derivedPostingForDraft(draft),
          postTo: draft.postTo,
          classifier: draft.classifier,
        },
        { coaAccounts }
      ),
    [
      draft.title,
      draft.recognitionMode,
      draft.recognitionSignals,
      draft.llmPrompt,
      draft.code,
      draft.classifier,
      draft.postTo,
      draft.klass,
      draft.playbookProfile,
      draft.posting,
      coaAccounts,
    ]
  );

  const bundleWarnings = useMemo(
    () => bundleConfigWarnings(draft, documentTypes),
    [draft, documentTypes]
  );

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
                  ? "Set recognition, then configure extraction, validation, playbook, and bundle rules before creating."
                  : "Update labels, recognition rules, extraction, and processing rules."}
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
          <DetailCard title="Identity" hint="Name, route, and enablement">
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5 sm:col-span-2">
                <FieldLabel htmlFor="dt-title">Document name</FieldLabel>
                <Input
                  id="dt-title"
                  value={draft.title}
                  onChange={(e) => onChange({ ...draft, title: e.target.value })}
                  className="h-9 text-sm"
                  placeholder="e.g. Handwritten GRN"
                />
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
              {(showAdvancedIdentity || !isNew) && (
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
              )}
              {isNew && !showAdvancedIdentity ? (
                <div className="sm:col-span-2">
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="h-8 text-xs"
                    onClick={() => setShowAdvancedIdentity(true)}
                  >
                    Show code, class, posting
                  </Button>
                </div>
              ) : null}
              {(showAdvancedIdentity || !isNew) && (
                <>
                  <div className="space-y-1.5">
                    <FieldLabel htmlFor="dt-klass">Class</FieldLabel>
                    <select
                      id="dt-klass"
                      value={draft.klass}
                      onChange={(e) =>
                        onChange(applyDraftChange(draft, { klass: e.target.value as DocumentTypeClass }))
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
                      value={derivedPostingForDraft(draft)}
                      disabled
                      aria-readonly="true"
                      className={cn(selectClass, "cursor-default opacity-80")}
                    >
                      <option value={derivedPostingForDraft(draft)}>
                        {derivedPostingForDraft(draft)}
                      </option>
                    </select>
                  </div>
                  <div className="space-y-1.5">
                    <FieldLabel htmlFor="dt-route">Workspace route</FieldLabel>
                    <select
                      id="dt-route"
                      value={draft.routeTarget}
                      onChange={(e) => {
                        const next = applyRoutePlaybookDefaults(draft, e.target.value);
                        const posting = derivePostingFromKlassAndProfile(
                          next.klass,
                          next.playbookProfile,
                          next.posting
                        );
                        onChange({ ...next, posting });
                      }}
                      className={selectClass}
                    >
                      {ROUTE_TARGETS.map((route) => (
                        <option key={route} value={route}>
                          {route}
                        </option>
                      ))}
                    </select>
                  </div>
                </>
              )}
            </div>
          </DetailCard>

          <DetailCard title="Recognition" hint="Recognition signals or AI prompt for classification">
            <DocumentRecognitionEditor draft={draft} onChange={onChange} />
          </DetailCard>

          <DetailCard title="Processing playbook" hint="Match and approval preset">
            <PlaybookPolicyEditor
              draft={draft}
              onChange={(next) => {
                const posting = derivePostingFromKlassAndProfile(
                  next.klass,
                  next.playbookProfile,
                  next.posting
                );
                onChange({ ...next, posting });
              }}
            />
          </DetailCard>

          <DetailCard title="Post to" hint="GL account from Settings → Chart of accounts">
            <DocumentTypePostToEditor
              draft={draft}
              onChange={(postTo) => onChange({ ...draft, postTo })}
            />
          </DetailCard>

          <DetailCard title="Extraction fields" hint="Star compulsory fields; drives VR03 and Approve">
            <ExtractionFieldsPicker
              id="dt-extraction-fields"
              extractionFields={draft.extractionFields}
              requiredFields={draft.requiredFields}
              onChange={({ extractionFields, requiredFields }) =>
                onChange({ ...draft, extractionFields, requiredFields })
              }
            />
          </DetailCard>

          <DetailCard title="Validation" hint="Finance checks; matching and bundle run from playbook">
            <ValidationRulesEditor
              documentTypeCode={draft.code}
              validationProfile={draft.validationProfile}
              validationRules={draft.validationRules}
              customValidationRules={draft.customValidationRules}
              requiredFields={draft.requiredFields}
              extractionFields={draft.extractionFields}
              onChange={(patch) => onChange({ ...draft, ...patch })}
            />
          </DetailCard>

          <DetailCard
            title="Supporting document requirements"
            hint="Dossier members on the same PO or SO"
          >
            <BundleRulesEditor
              draft={draft}
              documentTypes={documentTypes}
              bundleWarnings={bundleWarnings}
              onChange={onChange}
              selectClass={selectClass}
            />
          </DetailCard>
        </div>

        <div className="detail-dialog-footer flex-col items-stretch gap-3 sm:flex-row sm:items-center">
          {isNew ? (
            <ul className="flex-1 space-y-0.5 text-xs text-muted-foreground">
              {readiness.items.map((item) => (
                <li key={item.label} className={item.done ? "text-primary" : undefined}>
                  {item.done ? "✓" : "○"} {item.label}
                </li>
              ))}
            </ul>
          ) : (
            <span className="flex-1" />
          )}
          <div className="flex gap-2 justify-end">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onSave}
            disabled={
              !draft.code.trim() ||
              !draft.title.trim() ||
              codeTaken ||
              (isNew && !readiness.ready)
            }
            title={isNew && !readiness.ready ? "Complete the readiness checklist" : undefined}
          >
            {isNew ? "Create type" : "Save changes"}
          </Button>
          </div>
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
  const { data: coaAccounts = [] } = useChartOfAccounts();

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
          docType.llmPrompt,
          recognitionSummary(docType),
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
    const next = {
      ...editing,
      code: normalized,
      validationRules,
      bundleConditional: normalizeBundleConditional(editing.bundleConditional),
    };
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
          Configure document types for recognition, validation, Post to GL accounts, and supporting-document rules.
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
              </div>
              <div className="mt-1 text-sm font-medium text-foreground">
                {docType.title || docType.shortTitle}
              </div>
              <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                {recognitionSummary(docType)}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-2">
                <ClassBadge klass={docType.klass} />
                <ToneBadge tone={cardPostingTone(docType.posting)}>
                  Post: {docType.posting}
                </ToneBadge>
                {postToMissingOnCard(docType, coaAccounts) ? (
                  <ToneBadge tone="warn">GL missing</ToneBadge>
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
          coaAccounts={coaAccounts}
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
