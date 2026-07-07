import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import {
  bundleEditorMode,
  bundleMemberCandidates,
  bundleMemberDetailLabel,
  bundleRoleBadge,
  documentTypeLabel,
  dossierBookLabel,
  linkageReferenceLabel,
  normalizeBundleConditional,
  normalizeDtCodeList,
  PURCHASE_BUNDLE_ROLE_OPTIONS,
  SALES_BUNDLE_ROLE_OPTIONS,
  suggestedMandatoryBundleMembers,
  type PurchaseBundleRole,
  type SalesBundleRole,
} from "@/lib/documentBundleConfig";
import { effectivePlaybookProfile, playbookProfileLabel, reconcileDocumentTypeDraft } from "@/lib/documentPlaybookConfig";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import type { BundleConfigWarning } from "@/lib/documentTypeBundleValidation";

function FieldLabel({ htmlFor, children }: { htmlFor?: string; children: React.ReactNode }) {
  return (
    <label htmlFor={htmlFor} className="text-[11px] font-medium text-foreground">
      {children}
    </label>
  );
}

function BundleDtCodePicker({
  id,
  label,
  description,
  documentTypes,
  currentCode,
  consumerRouteTarget,
  value,
  onChange,
  tone = "primary",
}: {
  id: string;
  label: string;
  description?: string;
  documentTypes: DocumentTypeDefinition[];
  currentCode: string;
  consumerRouteTarget?: string;
  value: string[];
  onChange: (value: string[]) => void;
  tone?: "primary" | "warn";
}) {
  const selected = new Set(normalizeDtCodeList(value));
  const options = bundleMemberCandidates(documentTypes, currentCode, consumerRouteTarget);
  const isSales = consumerRouteTarget === "Sales Management";

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
          active: "border-[#9c4e2a] ds-warning-panel-strong ds-warning-text",
          idle: "border-border bg-muted/40 text-muted-foreground hover:border-[rgb(156_78_42/0.35)]",
        }
      : {
          active: "border-primary bg-primary/10 text-primary",
          idle: "border-border bg-muted/40 text-muted-foreground hover:border-primary/40",
        };

  return (
    <div className="space-y-2">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      {description ? (
        <p className="text-[11px] text-muted-foreground">{description}</p>
      ) : null}
      {options.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
          {isSales
            ? "Add SO or DN supporting types first."
            : "Add PO or GRN supporting types first."}
        </p>
      ) : (
        <div id={id} className="flex flex-wrap gap-2 rounded-md border border-input bg-background p-3">
          {options.map((row) => {
            const code = row.code.toUpperCase();
            const active = selected.has(code);
            const badge =
              bundleRoleBadge(row.purchaseBundleRole) || bundleRoleBadge(row.salesBundleRole);
            return (
              <button
                key={code}
                type="button"
                onClick={() => toggle(code)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-left text-[11px] font-medium transition-colors",
                  active ? toneClasses.active : toneClasses.idle
                )}
                title={row.title}
              >
                {badge ? (
                  <span className="rounded bg-background/60 px-1 py-0.5 text-[9px] font-semibold uppercase tracking-wide">
                    {badge}
                  </span>
                ) : null}
                <span>{documentTypeLabel(documentTypes, code)}</span>
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

function BundleWarnings({ warnings }: { warnings: BundleConfigWarning[] }) {
  if (!warnings.length) return null;
  return (
    <ul className="space-y-1 rounded-md border ds-warning-panel-strong px-3 py-2 text-xs ds-warning-text">
      {warnings.map((warning) => (
        <li key={warning.id}>{warning.message}</li>
      ))}
    </ul>
  );
}

export function BundleRulesDetailSection({
  docType,
  documentTypes,
}: {
  docType: DocumentTypeDefinition;
  documentTypes: DocumentTypeDefinition[];
}) {
  const mode = bundleEditorMode(docType);
  const conditionalDtCodes = normalizeBundleConditional(docType.bundleConditional);
  const profile = effectivePlaybookProfile(docType);
  const isSales = docType.routeTarget === "Sales Management";
  const dossierBook = dossierBookLabel(docType.routeTarget);

  if (mode === "inactive") {
    return (
      <p className="text-sm text-muted-foreground">
        Not used — {playbookProfileLabel(profile)} does not require a {dossierBook} on this type.
      </p>
    );
  }

  if (mode === "member") {
    const roleLabel =
      (isSales
        ? SALES_BUNDLE_ROLE_OPTIONS.find((row) => row.value === docType.salesBundleRole)?.label
        : PURCHASE_BUNDLE_ROLE_OPTIONS.find((row) => row.value === docType.purchaseBundleRole)
            ?.label) ?? "Not configured";
    return (
      <div className="space-y-2 text-sm">
        <p className="text-[11px] text-muted-foreground">Configured on the invoice type.</p>
        <p className="font-medium text-foreground">{roleLabel}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <p className="text-[11px] font-medium text-foreground">Required</p>
        <DetailChipList
          items={docType.bundleMandatory.map((code) =>
            bundleMemberDetailLabel(code, documentTypes)
          )}
          emptyLabel="None"
        />
      </div>
      {conditionalDtCodes.length > 0 ? (
        <div>
          <p className="text-[11px] font-medium text-foreground">Recommended</p>
          <DetailChipList
            tone="warn"
            items={conditionalDtCodes.map((code) => documentTypeLabel(documentTypes, code))}
            emptyLabel=""
          />
        </div>
      ) : null}
    </div>
  );
}

function DetailChipList({
  items,
  emptyLabel,
  tone = "neutral",
}: {
  items: string[];
  emptyLabel: string;
  tone?: "neutral" | "warn";
}) {
  if (!items.length) {
    return <p className="text-sm text-muted-foreground">{emptyLabel}</p>;
  }
  const toneClass =
    tone === "warn"
      ? "ds-warning-panel-strong border ds-warning-text"
      : "border-border bg-muted/40 text-foreground";
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <span
          key={item}
          className={cn(
            "inline-flex rounded-full border px-2.5 py-0.5 text-[11px] font-medium",
            toneClass
          )}
        >
          {item}
        </span>
      ))}
    </div>
  );
}

export function BundleRulesEditor({
  draft,
  documentTypes,
  bundleWarnings,
  onChange,
  selectClass,
}: {
  draft: DocumentTypeDefinition;
  documentTypes: DocumentTypeDefinition[];
  bundleWarnings: BundleConfigWarning[];
  onChange: (next: DocumentTypeDefinition) => void;
  selectClass: string;
}) {
  const mode = bundleEditorMode(draft);
  const conditionalDtCodes = normalizeBundleConditional(draft.bundleConditional);
  const profile = effectivePlaybookProfile(draft);
  const isSalesConsumer = draft.routeTarget === "Sales Management";
  const suggested = suggestedMandatoryBundleMembers(
    documentTypes,
    draft.code,
    draft.routeTarget
  );
  const bundlePairLabel = isSalesConsumer ? "SO + DN" : "PO + GRN";
  const linkageRef = linkageReferenceLabel(draft.routeTarget);

  if (mode === "inactive") {
    return (
      <div className="space-y-3">
        <BundleWarnings warnings={bundleWarnings} />
        <p className="text-sm text-muted-foreground">
          Not used — {playbookProfileLabel(profile)} does not require supporting documents on this
          type.
        </p>
      </div>
    );
  }

  if (mode === "member") {
    const isSalesMember = draft.routeTarget === "Sales Management";
    return (
      <div className="space-y-4">
        <BundleWarnings warnings={bundleWarnings} />
        <div className="space-y-1.5">
          <FieldLabel htmlFor="dt-bundle-role">Bundle role</FieldLabel>
          <p className="text-[11px] text-muted-foreground">
            How this type links on the {isSalesMember ? "SO" : "PO"}.
          </p>
          {isSalesMember ? (
            <select
              id="dt-bundle-role"
              value={draft.salesBundleRole}
              onChange={(e) =>
                onChange(
                  reconcileDocumentTypeDraft(
                    {
                      ...draft,
                      salesBundleRole: e.target.value as SalesBundleRole,
                    },
                    documentTypes
                  )
                )
              }
              className={selectClass}
            >
              {SALES_BUNDLE_ROLE_OPTIONS.map((row) => (
                <option key={row.value || "none"} value={row.value}>
                  {row.label}
                </option>
              ))}
            </select>
          ) : (
            <select
              id="dt-bundle-role"
              value={draft.purchaseBundleRole}
              onChange={(e) =>
                onChange(
                  reconcileDocumentTypeDraft(
                    {
                      ...draft,
                      purchaseBundleRole: e.target.value as PurchaseBundleRole,
                    },
                    documentTypes
                  )
                )
              }
              className={selectClass}
            >
              {PURCHASE_BUNDLE_ROLE_OPTIONS.map((row) => (
                <option key={row.value || "none"} value={row.value}>
                  {row.label}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <BundleWarnings warnings={bundleWarnings} />
      <p className="text-[11px] text-muted-foreground">
        Required because playbook: <span className="font-medium text-foreground">{playbookProfileLabel(profile)}</span>
        {" · "}
        Same {linkageRef} as this document.
      </p>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          {suggested.length > 0 &&
          normalizeDtCodeList(draft.bundleMandatory).length === 0 ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="ml-auto"
              onClick={() => onChange({ ...draft, bundleMandatory: suggested })}
            >
              Use {bundlePairLabel} from catalogue
            </Button>
          ) : null}
        </div>
        <BundleDtCodePicker
          id="dt-bundle-mandatory"
          label="Required supporting documents"
          description="Blocks posting until on the dossier."
          documentTypes={documentTypes}
          currentCode={draft.code}
          consumerRouteTarget={draft.routeTarget}
          value={draft.bundleMandatory}
          onChange={(bundleMandatory) => onChange({ ...draft, bundleMandatory })}
        />
      </div>

      <div className="space-y-3 border-t border-border/60 pt-4">
        <BundleDtCodePicker
          id="dt-bundle-conditional"
          label="Recommended companion document types"
          description="Warns if missing; does not block."
          documentTypes={documentTypes}
          currentCode={draft.code}
          consumerRouteTarget={draft.routeTarget}
          value={conditionalDtCodes}
          tone="warn"
          onChange={(dtCodes) =>
            onChange({
              ...draft,
              bundleConditional: normalizeDtCodeList(dtCodes),
            })
          }
        />
      </div>
    </div>
  );
}
