/** Bundle mandatory / conditional DT code helpers — align with backend playbook service. */

import {
  effectivePlaybookProfile,
  matchTabLabel,
  playbookPresetForProfile,
  type PlaybookProfile,
} from "@/lib/documentPlaybookConfig";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { isTransPosting } from "@/lib/documentTypeKlass";

export const ROUTE_PURCHASE = "Purchase Management";
export const ROUTE_SALES = "Sales Management";

export function isSalesManagementRoute(routeTarget?: string | null): boolean {
  return (routeTarget ?? "").trim() === ROUTE_SALES;
}

export function isPurchaseManagementRoute(routeTarget?: string | null): boolean {
  return (routeTarget ?? "").trim() === ROUTE_PURCHASE;
}

/** Short finance label for the dossier linkage key (PO vs SO). */
export function linkageReferenceShort(routeTarget?: string | null): string {
  return isSalesManagementRoute(routeTarget) ? "SO" : "PO";
}

/** Full label for linkage reference field in copy. */
export function linkageReferenceLabel(routeTarget?: string | null): string {
  return isSalesManagementRoute(routeTarget) ? "SO reference" : "PO reference";
}

/** Rule Book section title — avoids overloaded “bundle” term. */
export function supportingDocumentRequirementsTitle(): string {
  return "Supporting document requirements";
}

/** Pipeline stage — dossier completeness before posting. */
export function dossierCompletenessStageLabel(): string {
  return "Supporting documents";
}

/** Invoice drawer tab — legacy default assumes 3-way when match mode is unknown. */
export function threeWayMatchTabLabel(routeTarget?: string | null): string {
  const defaultMode = isSalesManagementRoute(routeTarget)
    ? "three_way_so_dn"
    : isPurchaseManagementRoute(routeTarget)
      ? "three_way_po_grn"
      : "three_way_po_grn";
  return matchTabLabel(routeTarget, defaultMode);
}

/** Finance book name for dossier copy. */
export function dossierBookLabel(routeTarget?: string | null): string {
  if (isSalesManagementRoute(routeTarget)) return "sales order dossier";
  if (isPurchaseManagementRoute(routeTarget)) return "purchase order dossier";
  return "document dossier";
}

/** Required supporting docs pill in dossier UI. */
export function requiredSupportingDocsLabel(present: number, required: number): string {
  return `${present}/${required} required supporting docs`;
}

const DT_CODE_PATTERN = /^DT-\d{2}$/i;

export type PurchaseBundleRole = "" | "po" | "grn";
export type SalesBundleRole = "" | "so" | "dn";

export type BundleEditorMode = "inactive" | "member" | "consumer";

export const PURCHASE_BUNDLE_ROLE_OPTIONS: Array<{ value: PurchaseBundleRole; label: string }> = [
  {
    value: "",
    label: "Classified copy on the same PO reference (by document type)",
  },
  { value: "po", label: "PO — purchase order register or uploaded PO copy" },
  { value: "grn", label: "GRN — goods receipt register or uploaded GRN copy" },
];

export const SALES_BUNDLE_ROLE_OPTIONS: Array<{ value: SalesBundleRole; label: string }> = [
  {
    value: "",
    label: "Classified copy on the same SO reference (by document type)",
  },
  { value: "so", label: "SO — sales order register or uploaded SO copy" },
  { value: "dn", label: "DN — delivery note register or uploaded DN copy" },
];

export function isDtCode(value: string): boolean {
  return DT_CODE_PATTERN.test(value.trim());
}

export function normalizeDtCode(value: string): string | null {
  const trimmed = value.trim().toUpperCase();
  return isDtCode(trimmed) ? trimmed : null;
}

export function normalizeDtCodeList(values: string[] | null | undefined): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of values ?? []) {
    const code = normalizeDtCode(raw);
    if (!code || seen.has(code)) continue;
    seen.add(code);
    out.push(code);
  }
  return out;
}

export function splitBundleItems(items: string[]): { dtCodes: string[]; advisories: string[] } {
  const dtCodes: string[] = [];
  const advisories: string[] = [];
  for (const raw of items) {
    const token = raw.trim();
    if (!token) continue;
    const code = normalizeDtCode(token);
    if (code) {
      if (!dtCodes.includes(code)) dtCodes.push(code);
    } else {
      advisories.push(token);
    }
  }
  return { dtCodes, advisories };
}

/** Recommended bundle members — document type codes only (legacy free-text lines stripped). */
export function normalizeBundleConditional(items: string[]): string[] {
  return splitBundleItems(items).dtCodes;
}

export function mergeBundleItems(dtCodes: string[], advisories: string[]): string[] {
  return [...normalizeDtCodeList(dtCodes), ...advisories.map((line) => line.trim()).filter(Boolean)];
}

export function documentTypeLabel(
  documentTypes: Array<{ code: string; shortTitle: string; title: string }>,
  code: string
): string {
  const row = documentTypes.find((dt) => dt.code.toUpperCase() === code.toUpperCase());
  if (!row) return code;
  return `${row.code} · ${row.title || row.shortTitle}`;
}

export function salesBundleRoleLabel(role: SalesBundleRole | string | undefined): string | null {
  const token = (role || "").trim().toLowerCase() as SalesBundleRole;
  const row = SALES_BUNDLE_ROLE_OPTIONS.find((option) => option.value === token);
  return row && row.value ? row.label : null;
}

export function purchaseBundleRoleLabel(role: PurchaseBundleRole | string | undefined): string | null {
  const token = (role || "").trim().toLowerCase() as PurchaseBundleRole;
  const row = PURCHASE_BUNDLE_ROLE_OPTIONS.find((option) => option.value === token);
  return row && row.value ? row.label : null;
}

export function bundleMemberDetailLabel(
  code: string,
  documentTypes: DocumentTypeDefinition[]
): string {
  const row = documentTypes.find((dt) => dt.code.toUpperCase() === code.toUpperCase());
  const base = documentTypeLabel(documentTypes, code);
  if (!row) return base;
  const purchaseRole = (row.purchaseBundleRole || "").trim().toLowerCase();
  if (purchaseRole === "po") return `${base} (PO register / upload)`;
  if (purchaseRole === "grn") return `${base} (GRN register / upload)`;
  const salesRole = (row.salesBundleRole || "").trim().toLowerCase();
  if (salesRole === "so") return `${base} (SO register / upload)`;
  if (salesRole === "dn") return `${base} (DN register / upload)`;
  return base;
}

/** Supporting purchase documents (PO copy, GRN) that link on a dossier. */
export function isPurchaseBundleMemberCandidate(
  docType: Pick<DocumentTypeDefinition, "code" | "klass" | "routeTarget" | "posting" | "purchaseBundleRole" | "enabled">
): boolean {
  if (docType.enabled === false) return false;
  const role = (docType.purchaseBundleRole || "").trim().toLowerCase();
  if (role === "po" || role === "grn") return true;
  return (
    !isTransPosting(docType) &&
    docType.routeTarget === "Purchase Management"
  );
}

/** Supporting sales documents (SO copy, DN) that link on a dossier. */
export function isSalesBundleMemberCandidate(
  docType: Pick<DocumentTypeDefinition, "code" | "klass" | "routeTarget" | "posting" | "salesBundleRole" | "enabled">
): boolean {
  if (docType.enabled === false) return false;
  const role = (docType.salesBundleRole || "").trim().toLowerCase();
  if (role === "so" || role === "dn") return true;
  return (
    !isTransPosting(docType) &&
    docType.routeTarget === "Sales Management"
  );
}

export function isBundleMemberCandidate(
  docType: Pick<
    DocumentTypeDefinition,
    | "code"
    | "klass"
    | "routeTarget"
    | "posting"
    | "purchaseBundleRole"
    | "salesBundleRole"
    | "enabled"
  >
): boolean {
  return isPurchaseBundleMemberCandidate(docType) || isSalesBundleMemberCandidate(docType);
}

export function playbookEnforcesBundle(
  docType: Pick<DocumentTypeDefinition, "playbookProfile">
): boolean {
  const profile = effectivePlaybookProfile(
    docType as DocumentTypeDefinition
  ) as PlaybookProfile;
  return playbookPresetForProfile(profile).enforceBundle;
}

/** How the Bundle rules panel should present for this document type. */
export function bundleEditorMode(
  draft: Pick<
    DocumentTypeDefinition,
    | "playbookProfile"
    | "posting"
    | "purchaseBundleRole"
    | "salesBundleRole"
    | "klass"
    | "routeTarget"
    | "bundleMandatory"
  >
): BundleEditorMode {
  const purchaseRole = (draft.purchaseBundleRole || "").trim().toLowerCase();
  if (purchaseRole === "po" || purchaseRole === "grn") return "member";

  const salesRole = (draft.salesBundleRole || "").trim().toLowerCase();
  if (salesRole === "so" || salesRole === "dn") return "member";

  if (
    !isTransPosting(draft) &&
    draft.routeTarget === "Purchase Management"
  ) {
    return "member";
  }
  if (
    !isTransPosting(draft) &&
    draft.routeTarget === "Sales Management"
  ) {
    return "member";
  }

  if (playbookEnforcesBundle(draft)) return "consumer";

  return "inactive";
}

export function bundleMandatoryMatchesSuggested(
  draft: DocumentTypeDefinition,
  documentTypes: DocumentTypeDefinition[]
): boolean {
  const mandatory = normalizeDtCodeList(draft.bundleMandatory);
  if (mandatory.length === 0) return false;
  const suggested = suggestedMandatoryBundleMembers(
    documentTypes,
    draft.code,
    draft.routeTarget
  );
  if (mandatory.length !== suggested.length) return false;
  return mandatory.every((code, index) => code === suggested[index]);
}

/** Align bundle mandatory/conditional with playbook-driven editor mode. */
export function reconcileBundleDraft(
  draft: DocumentTypeDefinition,
  documentTypes?: DocumentTypeDefinition[]
): DocumentTypeDefinition {
  const mode = bundleEditorMode(draft);
  const conditional = normalizeBundleConditional(draft.bundleConditional);

  if (mode === "inactive") {
    return {
      ...draft,
      bundleMandatory: [],
      bundleConditional: conditional,
    };
  }

  if (mode === "member") {
    return {
      ...draft,
      bundleMandatory: [],
      bundleConditional: [],
    };
  }

  const mandatory = normalizeDtCodeList(draft.bundleMandatory);
  if (mandatory.length === 0 && documentTypes?.length) {
    const suggested = suggestedMandatoryBundleMembers(
      documentTypes,
      draft.code,
      draft.routeTarget
    );
    if (suggested.length > 0) {
      return {
        ...draft,
        bundleMandatory: suggested,
        bundleConditional: conditional,
      };
    }
  }

  return {
    ...draft,
    bundleMandatory: mandatory,
    bundleConditional: conditional,
  };
}

export function bundleMemberCandidates(
  documentTypes: DocumentTypeDefinition[],
  currentCode: string,
  consumerRouteTarget?: string
): DocumentTypeDefinition[] {
  const exclude = currentCode.trim().toUpperCase();
  const consumerRoute = (consumerRouteTarget || "").trim();
  return documentTypes
    .filter((dt) => {
      if (dt.code.trim().toUpperCase() === exclude) return false;
      if (consumerRoute === "Sales Management") return isSalesBundleMemberCandidate(dt);
      if (consumerRoute === "Purchase Management") return isPurchaseBundleMemberCandidate(dt);
      return isBundleMemberCandidate(dt);
    })
    .sort((a, b) => {
      const roleOrder = (dt: DocumentTypeDefinition) => {
        const purchaseRole = (dt.purchaseBundleRole || "").toLowerCase();
        if (purchaseRole === "po") return 0;
        if (purchaseRole === "grn") return 1;
        const salesRole = (dt.salesBundleRole || "").toLowerCase();
        if (salesRole === "so") return 0;
        if (salesRole === "dn") return 1;
        return 2;
      };
      const byRole = roleOrder(a) - roleOrder(b);
      if (byRole !== 0) return byRole;
      return a.code.localeCompare(b.code);
    });
}

export function suggestedMandatoryBundleMembers(
  documentTypes: DocumentTypeDefinition[],
  currentCode: string,
  consumerRouteTarget?: string
): string[] {
  const route = (consumerRouteTarget || "").trim();
  if (route === "Sales Management") {
    const so = documentTypes.find(
      (dt) =>
        dt.enabled !== false &&
        (dt.salesBundleRole || "").toLowerCase() === "so" &&
        dt.code.trim().toUpperCase() !== currentCode.trim().toUpperCase()
    );
    const dn = documentTypes.find(
      (dt) =>
        dt.enabled !== false &&
        (dt.salesBundleRole || "").toLowerCase() === "dn" &&
        dt.code.trim().toUpperCase() !== currentCode.trim().toUpperCase()
    );
    return normalizeDtCodeList([so?.code ?? "", dn?.code ?? ""]);
  }

  const po = documentTypes.find(
    (dt) =>
      dt.enabled !== false &&
      (dt.purchaseBundleRole || "").toLowerCase() === "po" &&
      dt.code.trim().toUpperCase() !== currentCode.trim().toUpperCase()
  );
  const grn = documentTypes.find(
    (dt) =>
      dt.enabled !== false &&
      (dt.purchaseBundleRole || "").toLowerCase() === "grn" &&
      dt.code.trim().toUpperCase() !== currentCode.trim().toUpperCase()
  );
  return normalizeDtCodeList([po?.code ?? "", grn?.code ?? ""]);
}

export function bundleRoleBadge(
  role: PurchaseBundleRole | SalesBundleRole | string | undefined
): string | null {
  const token = (role || "").trim().toLowerCase();
  if (token === "po") return "PO";
  if (token === "grn") return "GRN";
  if (token === "so") return "SO";
  if (token === "dn") return "DN";
  return null;
}
