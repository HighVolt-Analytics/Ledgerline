/** Remove document types from tenant catalogues — mirrors backend document_type_lifecycle.py */

import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import type { RuleBookConfigState } from "@/lib/v4RuleBookTypes";
import { normalizeDtCodeList } from "@/lib/documentBundleConfig";

export function normalizeDocumentTypeCode(code: string | null | undefined): string {
  return (code ?? "").trim().toUpperCase();
}

function catalogueCodes(documentTypes: DocumentTypeDefinition[]): Set<string> {
  return new Set(
    documentTypes
      .map((dt) => normalizeDocumentTypeCode(dt.code))
      .filter(Boolean)
  );
}

export function scrubDocumentTypeReferences(
  state: Pick<RuleBookConfigState, "documentTypes" | "documentClassification">
): Pick<RuleBookConfigState, "documentTypes" | "documentClassification"> {
  const codes = catalogueCodes(state.documentTypes);
  const documentTypes = state.documentTypes.map((dt) => {
    const mandatory = normalizeDtCodeList(dt.bundleMandatory).filter((code) => codes.has(code));
    const conditional = dt.bundleConditional.filter((item) => {
      const token = item.trim();
      if (!token) return false;
      const normalized = normalizeDocumentTypeCode(token);
      if (/^DT-\d{2}$/i.test(normalized) && !codes.has(normalized)) return false;
      return true;
    });
    if (
      mandatory.length === dt.bundleMandatory.length &&
      conditional.length === dt.bundleConditional.length
    ) {
      return dt;
    }
    return { ...dt, bundleMandatory: mandatory, bundleConditional: conditional };
  });

  const unclassified = normalizeDocumentTypeCode(
    state.documentClassification?.unclassifiedDocumentTypeCode
  );
  const documentClassification =
    unclassified && !codes.has(unclassified)
      ? {
          ...state.documentClassification,
          unclassifiedDocumentTypeCode: "",
        }
      : state.documentClassification;

  return { documentTypes, documentClassification };
}

export function removeDocumentTypeFromCatalog(
  state: RuleBookConfigState,
  code: string
): RuleBookConfigState {
  const token = normalizeDocumentTypeCode(code);
  const documentTypes = state.documentTypes.filter(
    (dt) => normalizeDocumentTypeCode(dt.code) !== token
  );
  if (documentTypes.length === state.documentTypes.length) {
    return state;
  }
  const scrubbed = scrubDocumentTypeReferences({
    documentTypes,
    documentClassification: state.documentClassification,
  });
  return { ...state, ...scrubbed };
}
