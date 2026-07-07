import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

export function mergeDocumentTypePatch(
  documentTypes: DocumentTypeDefinition[],
  code: string,
  partial: Partial<DocumentTypeDefinition>
): DocumentTypeDefinition[] {
  const token = code.trim().toUpperCase();
  return documentTypes.map((dt) =>
    dt.code.trim().toUpperCase() === token ? { ...dt, ...partial } : dt
  );
}

export function shouldApplyRuleBookSaveResponse(
  responseGeneration: number,
  latestSaveGeneration: number
): boolean {
  return responseGeneration === latestSaveGeneration;
}
