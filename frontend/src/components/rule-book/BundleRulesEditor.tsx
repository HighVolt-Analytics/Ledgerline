import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import {
  bundleEditorMode,
  bundleMemberCandidates,
  bundleMemberDetailLabel,
  bundleRoleBadge,
  documentTypeLabel,
  mergeBundleItems,
  normalizeDtCodeList,
  playbookEnforcesBundle,
  PURCHASE_BUNDLE_ROLE_OPTIONS,
  splitBundleItems,
  suggestedMandatoryBundleMembers,
  type PurchaseBundleRole,
} from "@/lib/documentBundleConfig";
import { effectivePlaybookProfile, playbookProfileLabel } from "@/lib/documentPlaybookConfig";
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
  const options = bundleMemberCandidates(documentTypes, currentCode);

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
    <div className="space-y-2">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <p className="text-[11px] text-muted-foreground">{description}</p>
      {options.length === 0 ? (
        <p className="rounded-md border border-dashed border-border px-3 py-2 text-xs text-muted-foreground">
          Add supporting document types with a PO or GRN bundle link first (e.g. from the
          procurement starter pack).
        </p>
      ) : (
        <div id={id} className="flex flex-wrap gap-2 rounded-md border border-input bg-background p-3">
          {options.map((row) => {
            const code = row.code.toUpperCase();
            const active = selected.has(code);
            const badge = bundleRoleBadge(row.purchaseBundleRole);
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

function ListField({
  id,
  label,
  value,
  onChange,
  rows = 3,
}: {
  id: string;
  label: string;
  value: string[];
  onChange: (value: string[]) => void;
  rows?: number;
}) {
  const text = value.join("\n");
  return (
    <div className="space-y-1.5">
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <textarea
        id={id}
        rows={rows}
        value={text}
        onChange={(e) =>
          onChange(
            e.target.value
              .split("\n")
              .map((line) => line.trim())
              .filter(Boolean)
          )
        }
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
        placeholder="One advisory per line, e.g. Quality certificate"
      />
    </div>
  );
}

function BundleWarnings({ warnings }: { warnings: BundleConfigWarning[] }) {
  if (!warnings.length) return null;
  return (
    <ul className="space-y-1 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-900 dark:text-amber-100">
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
  const conditionalBundle = splitBundleItems(docType.bundleConditional);
  const profile = effectivePlaybookProfile(docType);

  if (mode === "inactive") {
    return (
      <p className="text-sm text-muted-foreground">
        Not used — {playbookProfileLabel(profile)} does not require a procurement dossier on this
        type.
      </p>
    );
  }

  if (mode === "member") {
    const roleLabel =
      PURCHASE_BUNDLE_ROLE_OPTIONS.find((row) => row.value === docType.purchaseBundleRole)?.label ??
      "Not configured";
    return (
      <div className="space-y-2 text-sm">
        <p className="text-muted-foreground">
          This type is a bundle member on PO dossiers. Other payable types reference it by code.
        </p>
        <p className="font-medium text-foreground">{roleLabel}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Payable type — documents on the same PO reference required before posting.
      </p>
      <div>
        <p className="text-[11px] font-medium text-foreground">Required (blocks posting)</p>
        <DetailChipList
          items={docType.bundleMandatory.map((code) =>
            bundleMemberDetailLabel(code, documentTypes)
          )}
          emptyLabel="None"
        />
      </div>
      {conditionalBundle.dtCodes.length || conditionalBundle.advisories.length ? (
        <div>
          <p className="text-[11px] font-medium text-foreground">Recommended (advisory)</p>
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
            <ul className="mt-2 space-y-1 text-sm text-muted-foreground">
              {conditionalBundle.advisories.map((item, index) => (
                <li key={index}>· {item}</li>
              ))}
            </ul>
          ) : null}
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
      ? "border-amber-500/30 bg-amber-500/10 text-amber-900 dark:text-amber-100"
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
  const conditionalBundle = splitBundleItems(draft.bundleConditional);
  const profile = effectivePlaybookProfile(draft);
  const suggested = suggestedMandatoryBundleMembers(documentTypes, draft.code);

  if (mode === "inactive") {
    return (
      <div className="space-y-3">
        <BundleWarnings warnings={bundleWarnings} />
        <div className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-3 text-sm text-muted-foreground">
          <p>
            Bundle rules do not apply to this document type. Processing playbook is{" "}
            <span className="font-medium text-foreground">{playbookProfileLabel(profile)}</span> —
            invoices are not held for missing PO dossier members.
          </p>
          <p className="mt-2 text-xs">
            To require PO + GRN on the same reference, set Processing playbook to PO goods or PO
            services and configure mandatory members on the payable invoice type.
          </p>
        </div>
      </div>
    );
  }

  if (mode === "member") {
    return (
      <div className="space-y-4">
        <BundleWarnings warnings={bundleWarnings} />
        <p className="text-xs text-muted-foreground">
          Supporting document linked on procurement dossiers. Payable invoice types list this code
          in their required bundle — they do not configure bundle rules here.
        </p>
        <div className="space-y-1.5">
          <FieldLabel htmlFor="dt-purchase-bundle-role">How this type is found on a PO</FieldLabel>
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
          <p className="text-[11px] text-muted-foreground">
            PO and GRN use the purchase register or uploaded copy. Other supporting types match by
            document type on the same PO reference.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <BundleWarnings warnings={bundleWarnings} />
      <p className="text-xs text-muted-foreground">
        Configure which documents must exist on the same PO reference before this type can post.
        {playbookEnforcesBundle(draft)
          ? ` Playbook ${playbookProfileLabel(profile)} enforces mandatory bundle members.`
          : ""}
      </p>

      <div className="space-y-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <FieldLabel htmlFor="dt-bundle-mandatory">Required before posting</FieldLabel>
          {suggested.length > 0 &&
          normalizeDtCodeList(draft.bundleMandatory).length === 0 ? (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => onChange({ ...draft, bundleMandatory: suggested })}
            >
              Use PO + GRN from catalogue
            </Button>
          ) : null}
        </div>
        <BundleDtCodePicker
          id="dt-bundle-mandatory"
          label="Mandatory dossier members"
          description="Blocks posting (VR-PB02) until each type is present on the PO reference."
          documentTypes={documentTypes}
          currentCode={draft.code}
          value={draft.bundleMandatory}
          onChange={(bundleMandatory) => onChange({ ...draft, bundleMandatory })}
        />
      </div>

      <div className="space-y-3 border-t border-border/60 pt-4">
        <p className="text-[11px] font-medium text-foreground">Recommended (advisory only)</p>
        <BundleDtCodePicker
          id="dt-bundle-conditional"
          label="Companion document types"
          description="Warns when missing (VR-PB04) but does not block posting."
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
          label="Free-text advisories"
          value={conditionalBundle.advisories}
          onChange={(advisories) =>
            onChange({
              ...draft,
              bundleConditional: mergeBundleItems(conditionalBundle.dtCodes, advisories),
            })
          }
        />
      </div>
    </div>
  );
}
