/** Bundle mandatory / conditional DT code helpers — align with backend playbook service. */

import {
  effectivePlaybookProfile,
  playbookPresetForProfile,
  type PlaybookProfile,
} from "@/lib/documentPlaybookConfig";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

const DT_CODE_PATTERN = /^DT-\d{2}$/i;

export type PurchaseBundleRole = "" | "po" | "grn";

export type BundleEditorMode = "inactive" | "member" | "consumer";

export const PURCHASE_BUNDLE_ROLE_OPTIONS: Array<{ value: PurchaseBundleRole; label: string }> = [
  { value: "", label: "By document type — match another invoice on the same PO" },
  { value: "po", label: "PO — purchase order register or PO upload" },
  { value: "grn", label: "GRN — goods receipt register or GRN upload" },
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

export function mergeBundleItems(dtCodes: string[], advisories: string[]): string[] {
  return [...normalizeDtCodeList(dtCodes), ...advisories.map((line) => line.trim()).filter(Boolean)];
}

export function documentTypeLabel(
  documentTypes: Array<{ code: string; shortTitle: string; title: string }>,
  code: string
): string {
  const row = documentTypes.find((dt) => dt.code.toUpperCase() === code.toUpperCase());
  if (!row) return code;
  return `${row.code} · ${row.shortTitle || row.title}`;
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
  if (!row?.purchaseBundleRole) return base;
  const roleHint =
    row.purchaseBundleRole === "po"
      ? "PO register / upload"
      : row.purchaseBundleRole === "grn"
        ? "GRN register / upload"
        : null;
  return roleHint ? `${base} (${roleHint})` : base;
}

function postingIsPayable(posting: string): boolean {
  const token = posting.trim().toLowerCase();
  return token === "yes" || token === "conditional" || token === "down-payment";
}

/** Supporting purchase documents (PO copy, GRN) that link on a dossier. */
export function isBundleMemberCandidate(
  docType: Pick<DocumentTypeDefinition, "code" | "klass" | "routeTarget" | "posting" | "purchaseBundleRole" | "enabled">
): boolean {
  if (docType.enabled === false) return false;
  const role = (docType.purchaseBundleRole || "").trim().toLowerCase();
  if (role === "po" || role === "grn") return true;
  const klass = (docType.klass || "").trim().toLowerCase();
  const posting = (docType.posting || "").trim().toLowerCase();
  return (
    klass === "supporting" &&
    docType.routeTarget === "Purchase Management" &&
    posting === "no"
  );
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
    | "klass"
    | "routeTarget"
    | "bundleMandatory"
  >
): BundleEditorMode {
  const role = (draft.purchaseBundleRole || "").trim().toLowerCase();
  if (role === "po" || role === "grn") return "member";

  const klass = (draft.klass || "").trim().toLowerCase();
  const posting = (draft.posting || "").trim().toLowerCase();
  if (
    klass === "supporting" &&
    draft.routeTarget === "Purchase Management" &&
    posting === "no"
  ) {
    return "member";
  }

  if (playbookEnforcesBundle(draft)) return "consumer";
  if (normalizeDtCodeList(draft.bundleMandatory).length > 0) return "consumer";
  if (postingIsPayable(draft.posting) && draft.routeTarget === "Purchase Management") {
    return "consumer";
  }

  return "inactive";
}

export function bundleMemberCandidates(
  documentTypes: DocumentTypeDefinition[],
  currentCode: string
): DocumentTypeDefinition[] {
  const exclude = currentCode.trim().toUpperCase();
  return documentTypes
    .filter((dt) => dt.code.trim().toUpperCase() !== exclude && isBundleMemberCandidate(dt))
    .sort((a, b) => {
      const roleOrder = (dt: DocumentTypeDefinition) => {
        const role = (dt.purchaseBundleRole || "").toLowerCase();
        if (role === "po") return 0;
        if (role === "grn") return 1;
        return 2;
      };
      const byRole = roleOrder(a) - roleOrder(b);
      if (byRole !== 0) return byRole;
      return a.code.localeCompare(b.code);
    });
}

export function suggestedMandatoryBundleMembers(
  documentTypes: DocumentTypeDefinition[],
  currentCode: string
): string[] {
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

export function bundleRoleBadge(role: PurchaseBundleRole | string | undefined): string | null {
  const token = (role || "").trim().toLowerCase();
  if (token === "po") return "PO";
  if (token === "grn") return "GRN";
  return null;
}
