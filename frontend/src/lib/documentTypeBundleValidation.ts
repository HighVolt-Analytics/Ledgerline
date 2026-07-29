import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import {
  bundleEditorMode,
  bundleMemberCandidates,
  normalizeDtCodeList,
  playbookEnforcesBundle,
} from "@/lib/documentBundleConfig";
import { DOCUMENT_TYPE_TEMPLATES } from "@/lib/documentTypeTemplates";
import { defaultPlaybookProfileForCode } from "@/lib/documentTypePlaybookDefaults";

export type BundleConfigWarning = {
  id: string;
  message: string;
};

function catalogueCodes(documentTypes: DocumentTypeDefinition[]): Set<string> {
  return new Set(
    documentTypes
      .map((dt) => dt.code.trim().toUpperCase())
      .filter(Boolean)
  );
}

function bundleRoleForMember(member: DocumentTypeDefinition): string {
  return (
    (member.salesBundleRole || "").trim() ||
    (member.purchaseBundleRole || "").trim()
  );
}

/** Catalogue-level health warnings (drift / duplicate roles) — report only. */
export function catalogueHealthWarnings(
  documentTypes: DocumentTypeDefinition[]
): BundleConfigWarning[] {
  const warnings: BundleConfigWarning[] = [];
  const roleOwners = new Map<string, string>();

  for (const dt of documentTypes) {
    if (!dt.enabled) continue;
    const code = dt.code.trim().toUpperCase();
    const purchaseRole = (dt.purchaseBundleRole || "").trim().toLowerCase();
    const salesRole = (dt.salesBundleRole || "").trim().toLowerCase();
    for (const [kind, role] of [
      ["purchase", purchaseRole],
      ["sales", salesRole],
    ] as const) {
      if (!role) continue;
      if (kind === "purchase" && role !== "po" && role !== "grn") continue;
      if (kind === "sales" && role !== "so" && role !== "dn") continue;
      const key = `${kind}:${role}`;
      const prior = roleOwners.get(key);
      if (prior) {
        warnings.push({
          id: `duplicate-role-${key}-${code}`,
          message: `${code} and ${prior} both claim the ${role.toUpperCase()} bundle role — keep only one enabled.`,
        });
      } else {
        roleOwners.set(key, code);
      }
    }

    const matrix = (dt.matrixTemplateCode || "").trim().toUpperCase();
    if (!matrix) continue;
    const template = DOCUMENT_TYPE_TEMPLATES.find((row) => row.id === matrix);
    if (!template || template.id === "custom") continue;
    const shippedProfile = defaultPlaybookProfileForCode(matrix);
    const profile = (dt.playbookProfile || "").trim().toLowerCase();
    const shippedPurchase = (template.purchaseBundleRole || "").trim().toLowerCase();
    const shippedSales = (template.salesBundleRole || "").trim().toLowerCase();
    if (shippedProfile && profile && profile !== shippedProfile) {
      warnings.push({
        id: `matrix-drift-playbook-${code}`,
        message: `${code} is linked to matrix ${matrix} but playbook is ${profile} (shipped ${shippedProfile}) — detach or restore.`,
      });
    }
    if (purchaseRole !== shippedPurchase || salesRole !== shippedSales) {
      warnings.push({
        id: `matrix-drift-role-${code}`,
        message: `${code} is linked to matrix ${matrix} but bundle role drifted from the shipped template.`,
      });
    }
  }

  return warnings;
}

/** Rule Book warnings for finance-standard bundle configuration. */
export function bundleConfigWarnings(
  draft: DocumentTypeDefinition,
  documentTypes: DocumentTypeDefinition[]
): BundleConfigWarning[] {
  const mode = bundleEditorMode(draft);
  if (mode === "inactive") return [];

  const warnings: BundleConfigWarning[] = [];
  const codes = catalogueCodes(documentTypes);
  const self = draft.code.trim().toUpperCase();
  const mandatory = normalizeDtCodeList(draft.bundleMandatory);
  const isSales = draft.routeTarget === "Sales Management";
  const pairLabel = isSales ? "SO/DN" : "PO/GRN";
  const registerLabel = isSales ? "SO and DN" : "PO and GRN";

  if (mode === "member") {
    const role = isSales
      ? (draft.salesBundleRole || "").trim().toLowerCase()
      : (draft.purchaseBundleRole || "").trim().toLowerCase();
    if (!role) {
      warnings.push({
        id: "member-role-missing",
        message: isSales
          ? "Set SO or DN link so customer invoice types can verify this document on the dossier (register, upload, or classified copy)."
          : "Set PO or GRN link so payable types can verify this document on the dossier (register, upload, or classified copy).",
      });
    }
    return warnings;
  }

  if (playbookEnforcesBundle(draft) && mandatory.length === 0) {
    warnings.push({
      id: "enforce-bundle-empty",
      message: isSales
        ? "This playbook enforces supporting document completeness — add required SO/DN members or use “Use SO + DN from catalogue”."
        : "This playbook enforces supporting document completeness — add required PO/GRN members or use “Use PO + GRN from catalogue”.",
    });
  }

  const memberPool = bundleMemberCandidates(documentTypes, draft.code, draft.routeTarget);
  if (mandatory.length > 0 && memberPool.length === 0) {
    warnings.push({
      id: "no-bundle-members-in-catalogue",
      message: `No supporting types with a ${pairLabel} bundle link exist yet — create ${registerLabel} types first.`,
    });
  }

  for (const code of mandatory) {
    if (!codes.has(code)) {
      warnings.push({
        id: `missing-member-${code}`,
        message: `${code} is not in this catalogue — add the type or remove the reference.`,
      });
      continue;
    }
    const member = documentTypes.find((dt) => dt.code.trim().toUpperCase() === code);
    if (member && !bundleRoleForMember(member)) {
      warnings.push({
        id: `no-role-${code}`,
        message: isSales
          ? `${code} has no SO/DN bundle link — open that type and set how it is found on a sales order.`
          : `${code} has no PO/GRN bundle link — open that type and set how it is found on a PO.`,
      });
    }
  }

  if (mandatory.includes(self)) {
    warnings.push({
      id: "self-mandatory",
      message: "A document type cannot require itself in the bundle.",
    });
  }

  return warnings;
}
