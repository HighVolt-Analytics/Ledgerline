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
  linkageReferenceShort,
  mergeBundleItems,
  normalizeDtCodeList,
  playbookEnforcesBundle,
  PURCHASE_BUNDLE_ROLE_OPTIONS,
  SALES_BUNDLE_ROLE_OPTIONS,
  splitBundleItems,
  suggestedMandatoryBundleMembers,
  supportingDocumentRequirementsTitle,
  threeWayMatchTabLabel,
  type PurchaseBundleRole,
  type SalesBundleRole,
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
  consumerRouteTarget,
  value,
  onChange,
  tone = "primary",
}: {
  id: string;
  label: string;
  description: string;
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
          {isSales
            ? "Add supporting document types with an SO or DN bundle link first (e.g. from the sales starter pack)."
            : "Add supporting document types with a PO or GRN bundle link first (e.g. from the procurement starter pack)."}
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
  const isSales = docType.routeTarget === "Sales Management";
  const linkageRef = linkageReferenceLabel(docType.routeTarget);
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
        <p className="text-muted-foreground">
          Supporting document on the {dossierBook}.{" "}
          {isSales ? "Customer invoice" : "Payable invoice"} types list this code as a required
          supporting document.
        </p>
        <p className="font-medium text-foreground">{roleLabel}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {isSales ? "Customer invoice" : "Payable invoice"} — required supporting documents on the
        same {linkageRef} before posting. (Separate from 3-way qty/price match in{" "}
        {isSales ? "Sales" : "Purchase"} Management.)
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
  const isSalesConsumer = draft.routeTarget === "Sales Management";
  const suggested = suggestedMandatoryBundleMembers(
    documentTypes,
    draft.code,
    draft.routeTarget
  );
  const linkageLabel = linkageReferenceShort(draft.routeTarget);
  const linkageRef = linkageReferenceLabel(draft.routeTarget);
  const bundlePairLabel = isSalesConsumer ? "SO + DN" : "PO + GRN";
  const dossierBook = dossierBookLabel(draft.routeTarget);

  if (mode === "inactive") {
    return (
      <div className="space-y-3">
        <BundleWarnings warnings={bundleWarnings} />
        <div className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-3 text-sm text-muted-foreground">
          <p>
            Supporting document requirements do not apply to this type. Processing playbook is{" "}
            <span className="font-medium text-foreground">{playbookProfileLabel(profile)}</span> —
            invoices are not held for missing {dossierBook} members.
          </p>
          <p className="mt-2 text-xs">
            To require {bundlePairLabel} on the same {linkageRef}, set Processing playbook to{" "}
            {isSalesConsumer ? "AR goods (3-way)" : "PO goods or PO services"} and configure
            required supporting documents on the {isSalesConsumer ? "customer" : "payable"}{" "}
            invoice type.
          </p>
        </div>
      </div>
    );
  }

  if (mode === "member") {
    const isSalesMember = draft.routeTarget === "Sales Management";
    return (
      <div className="space-y-4">
        <BundleWarnings warnings={bundleWarnings} />
        <p className="text-xs text-muted-foreground">
          Supporting document on the {dossierBookLabel(draft.routeTarget)}.{" "}
          {isSalesMember ? "Customer invoice" : "Payable invoice"} types list this code in their
          required supporting documents — they are configured on the invoice type, not here.
        </p>
        <div className="space-y-1.5">
          <FieldLabel htmlFor="dt-bundle-role">
            How this type is found on a {isSalesMember ? "sales order" : "PO"}
          </FieldLabel>
          {isSalesMember ? (
            <select
              id="dt-bundle-role"
              value={draft.salesBundleRole}
              onChange={(e) =>
                onChange({
                  ...draft,
                  salesBundleRole: e.target.value as SalesBundleRole,
                })
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
          )}
          <p className="text-[11px] text-muted-foreground">
            {isSalesMember
              ? "SO and DN use the sales register or uploaded copy. Other supporting types match by document type on the same SO reference."
              : "PO and GRN use the purchase register or uploaded copy. Other supporting types match by document type on the same PO reference."}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <BundleWarnings warnings={bundleWarnings} />
      <p className="text-xs text-muted-foreground">
        <strong className="font-medium text-foreground">Dossier complete</strong> = required
        supporting documents on file on the same {linkageRef}.{" "}
        <strong className="font-medium text-foreground">3-way match</strong> = quantities and prices
        agree across order, receipt/delivery, and invoice (checked in{" "}
        {isSalesConsumer ? "Sales" : "Purchase"} Management).
        {playbookEnforcesBundle(draft)
          ? ` Playbook ${playbookProfileLabel(profile)} enforces required supporting documents.`
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
              Use {bundlePairLabel} from catalogue
            </Button>
          ) : null}
        </div>
        <BundleDtCodePicker
          id="dt-bundle-mandatory"
          label="Required supporting documents"
          description={`Blocks posting (VR-PB02) until each type is present on the ${linkageRef}.`}
          documentTypes={documentTypes}
          currentCode={draft.code}
          consumerRouteTarget={draft.routeTarget}
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
          consumerRouteTarget={draft.routeTarget}
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
