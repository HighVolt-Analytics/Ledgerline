import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import {
  bundleEditorMode,
  bundleMemberCandidates,
  normalizeDtCodeList,
  playbookEnforcesBundle,
} from "@/lib/documentBundleConfig";

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

  if (mode === "member") {
    const role = (draft.purchaseBundleRole || "").trim().toLowerCase();
    if (!role) {
      warnings.push({
        id: "member-role-missing",
        message:
          "Set PO or GRN link so payable types can verify this document on the dossier (register, upload, or classified copy).",
      });
    }
    return warnings;
  }

  if (playbookEnforcesBundle(draft) && mandatory.length === 0) {
    warnings.push({
      id: "enforce-bundle-empty",
      message:
        "This playbook enforces bundle completeness — add mandatory PO/GRN members or use “Use PO + GRN from catalogue”.",
    });
  }

  const memberPool = bundleMemberCandidates(documentTypes, draft.code);
  if (mandatory.length > 0 && memberPool.length === 0) {
    warnings.push({
      id: "no-bundle-members-in-catalogue",
      message:
        "No supporting types with a PO/GRN bundle link exist yet — create PO and GRN types first.",
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
    if (member && !(member.purchaseBundleRole || "").trim()) {
      warnings.push({
        id: `no-role-${code}`,
        message: `${code} has no PO/GRN bundle link — open that type and set how it is found on a PO.`,
      });
    }
  }

  const dangling = mandatory.filter((code) => code !== self && !codes.has(code));
  if (dangling.length) {
    warnings.push({
      id: "dangling-bundle",
      message: `Saving will drop bundle references to missing types: ${dangling.join(", ")}.`,
    });
  }

  return warnings;
}
