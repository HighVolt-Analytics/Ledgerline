/**
 * Document type templates for the Rule Book catalogue.
 * Built from the global industry dictionary (document_type_dictionary.json).
 */

import {
  DICTIONARY_VERSION,
  DOCUMENT_TYPE_TEMPLATES,
  type DocumentTypeTemplate,
  type DocumentTypeTemplateId,
  dictionaryIndustries,
  dictionaryMasterClasses,
  getDocumentTypeTemplate,
} from "@/lib/documentTypeDictionary";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import {
  createBlankDocumentType,
  emptyDocumentTypePostTo,
  nextOrgDocumentTypeCode,
  type DocumentTypePostToSuggestion,
} from "@/lib/v5DocumentTypes";
import { standardCatalogueKeysFromDictionaryHints } from "@/lib/documentExtractionFields";
import {
  resolvedExtractionFieldsFromMapping,
  unresolvedExtractionHintsFromMapping,
} from "@/lib/extractionFieldMapping";

export type {
  DocumentTypeTemplate,
  DocumentTypeTemplateId,
};

export {
  DICTIONARY_VERSION,
  DOCUMENT_TYPE_TEMPLATES,
  dictionaryIndustries,
  dictionaryMasterClasses,
  getDocumentTypeTemplate,
};

/** Org catalogue codes always follow the org sequence — never the dictionary code. */
function orgCodeForNewType(existing: DocumentTypeDefinition[]): string {
  return nextOrgDocumentTypeCode(existing);
}

export function documentTypeFromTemplate(
  templateId: DocumentTypeTemplateId,
  existing: DocumentTypeDefinition[]
): DocumentTypeDefinition {
  const template = getDocumentTypeTemplate(templateId);
  const base = createBlankDocumentType(existing);
  const code = orgCodeForNewType(existing);

  if (templateId === "custom" || !template.dictionaryCode) {
    return {
      ...base,
      code,
      enabled: false,
    };
  }

  return {
    ...base,
    code,
    title: template.label,
    shortTitle: template.label,
    klass: template.klass,
    posting: template.posting,
    recognitionMode: "prompt",
    recognitionSignals: [],
    llmPrompt: template.llmPrompt,
    routeTarget: template.routeTarget,
    counterpartyType: template.counterpartyType,
    enabled: template.enabled,
    playbookProfile: template.playbookProfile,
    matchPolicy: { mode: template.matchMode },
    approvalPolicy: {
      mode: template.approvalMode,
      requireApprovalForUnmatched: template.requireApprovalNoMatchEvidence,
      requireApprovalForUnverifiedCounterparty: template.requireApprovalNewMaster,
    },
    validationRules: [...template.validationRules],
    extractionFields: resolveAdoptExtractionFields(template),
    extractionFieldsSuggestion: extractionFieldsSuggestionFromTemplate(template),
    requiredFields: [],
    absentFields: [],
    minRouteConfidence: 0.65,
    validationProfile: "",
    matrixTemplateCode: "",
    sourceDictionaryCode: template.dictionaryCode,
    createdFromDictionaryVersion: DICTIONARY_VERSION,
    compulsoryFieldsPresent: template.compulsoryFieldsPresent,
    compulsoryFieldsSeverity: template.compulsoryFieldsSeverity,
    budgetControl: template.budgetControl,
    advanceControl: template.advanceControl,
    postTo: emptyDocumentTypePostTo(),
    postToSuggestion: postToSuggestionFromTemplate(template),
    classifier: {
      ...base.classifier,
      enabled: false,
    },
  };
}

function resolveAdoptExtractionFields(template: DocumentTypeTemplate): string[] {
  const fromMapping = resolvedExtractionFieldsFromMapping(template.dictionaryCode);
  if (fromMapping.length) return fromMapping;
  // Fallback when mapping entry is missing: exact/near-exact catalogue matches only.
  return standardCatalogueKeysFromDictionaryHints(template.extractionFields);
}

function extractionFieldsSuggestionFromTemplate(template: DocumentTypeTemplate): string[] | undefined {
  const prose = (template.extractionFields ?? [])
    .map((row) => String(row ?? "").trim())
    .filter(Boolean);
  const unresolved = unresolvedExtractionHintsFromMapping(template.dictionaryCode);
  const seen = new Set<string>();
  const rows: string[] = [];
  for (const row of [...prose, ...unresolved]) {
    if (seen.has(row)) continue;
    seen.add(row);
    rows.push(row);
  }
  return rows.length ? rows : undefined;
}

/** Stored adopt hint, or lookup from dictionary via sourceDictionaryCode. */
export function resolveExtractionFieldsSuggestionForDocumentType(
  definition: Pick<DocumentTypeDefinition, "extractionFieldsSuggestion" | "sourceDictionaryCode">
): string[] {
  const stored = (definition.extractionFieldsSuggestion ?? [])
    .map((row) => String(row ?? "").trim())
    .filter(Boolean);
  if (stored.length) return stored;
  const dictionaryCode = definition.sourceDictionaryCode?.trim().toUpperCase();
  if (!dictionaryCode) return [];
  const template = DOCUMENT_TYPE_TEMPLATES.find((row) => row.dictionaryCode === dictionaryCode);
  if (!template) return [];
  return extractionFieldsSuggestionFromTemplate(template) ?? [];
}

function postToSuggestionFromTemplate(template: DocumentTypeTemplate): DocumentTypePostToSuggestion | undefined {
  const ledger = template.postTo.ledger.trim();
  const subLedger = template.postTo.subLedger.trim();
  if (!ledger && !subLedger) return undefined;
  return { ledger: template.postTo.ledger, subLedger: template.postTo.subLedger };
}

/** Format dictionary post-to guidance for Rule Book hints. */
export function formatPostToSuggestionHint(
  suggestion: DocumentTypePostToSuggestion | undefined
): string {
  if (!suggestion) return "";
  const ledger = suggestion.ledger.trim();
  const subLedger = suggestion.subLedger.trim();
  if (ledger && subLedger) return `${ledger} / ${subLedger}`;
  return ledger || subLedger;
}

/** Stored adopt hint, or lookup from dictionary via sourceDictionaryCode. */
export function resolvePostToSuggestionForDocumentType(
  definition: Pick<DocumentTypeDefinition, "postToSuggestion" | "sourceDictionaryCode">
): DocumentTypePostToSuggestion | undefined {
  const stored = definition.postToSuggestion;
  if (stored && (stored.ledger.trim() || stored.subLedger.trim())) {
    return stored;
  }
  const dictionaryCode = definition.sourceDictionaryCode?.trim().toUpperCase();
  if (!dictionaryCode) return undefined;
  const template = DOCUMENT_TYPE_TEMPLATES.find((row) => row.dictionaryCode === dictionaryCode);
  if (!template) return undefined;
  return postToSuggestionFromTemplate(template);
}

export function inferTemplateIdFromDefinition(
  definition: Pick<DocumentTypeDefinition, "sourceDictionaryCode" | "matrixTemplateCode">
): DocumentTypeTemplateId {
  const dictionaryCode = definition.sourceDictionaryCode?.trim().toUpperCase();
  if (dictionaryCode) {
    const match = DOCUMENT_TYPE_TEMPLATES.find((row) => row.dictionaryCode === dictionaryCode);
    if (match && match.id !== "custom") return match.id;
  }
  return "custom";
}
