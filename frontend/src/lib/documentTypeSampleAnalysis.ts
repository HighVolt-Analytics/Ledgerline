/**

 * Sample-file analysis for document type cards (Rule Book editor).

 */



import type { RecognitionSignalId } from "@/lib/documentClassifierBuilder";

import {

  buildClassifierFromSignals,

  type ClassifierLayout,

} from "@/lib/documentClassifierBuilder";

import { getDocumentTypeTemplate, type DocumentTypeTemplateId } from "@/lib/documentTypeTemplates";

import { normalizeExtractionFieldKeys, extractionFieldLabel } from "@/lib/documentExtractionFields";

import {
  playbookPresetForProfile,
  PLAYBOOK_PROFILE_OPTIONS,
  type ApprovalMode,
  type MatchMode,
  type PlaybookProfile,
} from "@/lib/documentPlaybookConfig";

import type { PurchaseBundleRole } from "@/lib/documentBundleConfig";

import type { ValidationRuleConfig } from "@/lib/documentValidationChecks";

import type {
  DocumentTypeDefinition,
  DocumentTypeSampleAnalysis,
  DocumentTypeClass,
} from "@/lib/v5DocumentTypes";

import { api, ApiError } from "@/api/client";
import {
  isKnownRecognitionSignal,
  weakSignalSet,
} from "@/lib/recognitionSignalCatalog";

export type DocumentTypeSampleFileResult = {
  filename: string;

  recognition_signals: string[];

  extraction_fields: string[];

  document_heading?: string | null;

  parse_confidence?: string | null;

  routed_code?: string | null;

  routed_confidence?: number | null;

  route_needs_review?: boolean;

  route_conflicts?: string[];

  matches_expected?: boolean | null;

  route_alternatives?: Array<{

    code: string;

    confidence: number;

    reason: string;

    needs_review?: boolean;

    priority?: number;

  }>;

  signal_details?: RecognitionSignalDetail[];

  suggested_signals?: RecognitionSignalDetail[];

};



export type ValidationRuleProposal = {

  code: string;

  enabled: boolean;

  severity: "block" | "warn";

};



export type RecognitionSignalDetail = {
  signal_id: string;
  label: string;
  hint?: string;
  channel?: string;
  strength?: string;
  example?: string;
  detected?: boolean;
};

export type CatalogueMatchCandidate = {
  code: string;
  title: string;
  similarity: number;
  reason?: string;
};

export type DocumentTypeSampleProposal = {

  recognition_signals: string[];

  classifier_layout: ClassifierLayout;

  extraction_fields: string[];

  required_fields: string[];

  absent_fields: string[];

  one_line: string;

  suggested_title?: string | null;

  suggested_short_title?: string | null;

  klass: string;

  posting: string;

  route_target: string;

  playbook_profile: string;

  purchase_bundle_role: string;

  match_mode: MatchMode;

  approval_mode: ApprovalMode;

  validation_rules: ValidationRuleProposal[];

  bundle_mandatory: string[];

  bundle_conditional: string[];

  min_route_confidence: number;

  samples: DocumentTypeSampleFileResult[];

  notes: string[];

  validation_profile: string;

  catalogue_matches?: CatalogueMatchCandidate[];

  recognition_signal_details?: RecognitionSignalDetail[];

  suggested_signals?: RecognitionSignalDetail[];

  proposal_source?: string;

  reasoning?: string | null;

  apply_ready?: boolean;

  apply_block_reason?: string | null;

};

/** Shipped matrix template that best matches a sample-analysis playbook (simple-mode UI). */
const PLAYBOOK_MATRIX_TEMPLATE: Partial<Record<PlaybookProfile, DocumentTypeTemplateId>> = {
  po_goods: "DT-01",
  po_services: "DT-01",
  direct_expense: "DT-21",
  credit_adjustment: "DT-04",
  debit_note: "DT-05",
  pre_transactional: "DT-06",
  import_dossier: "DT-10",
  freight_logistics: "DT-09",
  intercompany: "DT-11",
  employee_claim: "DT-12",
  supporting: "DT-02",
  master_data: "DT-23",
  non_actionable: "DT-24",
  compliance_route: "DT-25",
  reconciliation: "DT-13",
  informational: "DT-13",
  standard_transactional: "DT-21",
};

function proposalSignalsForApply(proposal: DocumentTypeSampleProposal): RecognitionSignalId[] {
  const weakSignals = weakSignalSet();
  const detected = normalizeSignals(proposal.recognition_signals ?? []);
  const strongDetected = detected.filter((id) => !weakSignals.has(id));
  if (strongDetected.length > 0) {
    return detected;
  }
  const fromSuggested = (proposal.suggested_signals ?? [])
    .map((row) => row.signal_id)
    .filter(
      (id): id is RecognitionSignalId =>
        isKnownRecognitionSignal(id) && !weakSignals.has(id as RecognitionSignalId)
    );
  return [...new Set([...detected, ...fromSuggested])];
}

function resolveTemplateIdForApply(
  templateId: DocumentTypeTemplateId,
  proposal: DocumentTypeSampleProposal,
  draft: DocumentTypeDefinition
): DocumentTypeTemplateId {
  const stored = draft.matrixTemplateCode?.trim().toUpperCase();
  if (stored && stored !== "CUSTOM") {
    const fromStored = getDocumentTypeTemplate(stored as DocumentTypeTemplateId);
    if (fromStored.signals.length > 0) {
      return stored as DocumentTypeTemplateId;
    }
  }
  if (templateId !== "custom") {
    return templateId;
  }
  const playbook = asPlaybookProfile(proposal.playbook_profile ?? "");
  const mapped = PLAYBOOK_MATRIX_TEMPLATE[playbook];
  if (mapped) {
    return mapped;
  }
  return templateId;
}



export function buildSampleAnalysisRecord(
  filenames: string[],
  proposal: DocumentTypeSampleProposal,
  options?: { afterApply?: boolean }
): DocumentTypeSampleAnalysis {
  return {
    analyzedAt: new Date().toISOString(),
    filenames,
    fileCount: filenames.length,
    recognitionSignals: options?.afterApply
      ? proposalSignalsForApply(proposal)
      : normalizeSignals(proposal.recognition_signals ?? []),
  };
}



export function markSampleAnalysisApplied(
  record: DocumentTypeSampleAnalysis
): DocumentTypeSampleAnalysis {
  return { ...record, appliedAt: new Date().toISOString() };
}



export function formatSampleAnalysisWhen(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}



function normalizeSignals(values: string[]): RecognitionSignalId[] {

  return values.filter((id): id is RecognitionSignalId => isKnownRecognitionSignal(id));

}



function isPlaceholderTitle(value: string): boolean {

  const token = value.trim().toLowerCase();

  return (
    token === "new document type" ||
    token === "new type" ||
    token === "custom type" ||
    token.startsWith("custom type ")
  );

}



function isPlaceholderOneLine(value: string): boolean {

  const token = value.trim().toLowerCase();

  return (

    !token ||

    token === "describe how this document type is identified and processed."

  );

}



function asPlaybookProfile(value: string): PlaybookProfile {

  const token = value.trim().toLowerCase();

  if (PLAYBOOK_PROFILE_OPTIONS.some((option) => option.value === token)) {

    return token as PlaybookProfile;

  }

  return "standard_transactional";

}



function proposalValidationRules(proposal: DocumentTypeSampleProposal): ValidationRuleConfig[] {

  return (proposal.validation_rules ?? []).map((row) => ({

    code: row.code,

    enabled: row.enabled,

    severity: row.severity,

  }));

}



export function mergeSampleProposalIntoDraft(

  draft: DocumentTypeDefinition,

  proposal: DocumentTypeSampleProposal,

  templateId: DocumentTypeTemplateId

): DocumentTypeDefinition {

  const resolvedTemplateId = resolveTemplateIdForApply(templateId, proposal, draft);

  const template = getDocumentTypeTemplate(resolvedTemplateId);

  const signalIds = proposalSignalsForApply(proposal);

  const layout = proposal.classifier_layout ?? template.classifierLayout;

  const hasSignals = signalIds.length > 0;

  const playbookProfile = asPlaybookProfile(proposal.playbook_profile);

  const preset = playbookPresetForProfile(playbookProfile);



  const classifier =

    hasSignals

      ? buildClassifierFromSignals(signalIds, layout, {

          priority: draft.classifier.priority || template.classifierPriority,

          enabled: true,

          confidence: 0.85,

        })

      : { ...draft.classifier, enabled: draft.classifier.enabled };



  return {

    ...draft,

    title:

      proposal.suggested_title && isPlaceholderTitle(draft.title)

        ? proposal.suggested_title

        : draft.title,

    shortTitle:

      proposal.suggested_short_title && isPlaceholderTitle(draft.shortTitle)

        ? proposal.suggested_short_title

        : draft.shortTitle,

    oneLine:

      hasSignals && proposal.one_line && isPlaceholderOneLine(draft.oneLine)

        ? proposal.one_line

        : draft.oneLine,

    klass: hasSignals ? (proposal.klass as DocumentTypeClass) : draft.klass,

    posting: hasSignals ? proposal.posting : draft.posting,

    routeTarget: hasSignals ? proposal.route_target : draft.routeTarget,

    playbookProfile: hasSignals ? playbookProfile : draft.playbookProfile,

    matchPolicy: hasSignals ? { mode: proposal.match_mode as MatchMode } : draft.matchPolicy,

    approvalPolicy: hasSignals

      ? { mode: (proposal.approval_mode || preset.approvalMode) as ApprovalMode }

      : draft.approvalPolicy,

    purchaseBundleRole: (proposal.purchase_bundle_role || draft.purchaseBundleRole) as PurchaseBundleRole,

    validationProfile: hasSignals ? proposal.validation_profile : draft.validationProfile,

    validationRules: hasSignals ? proposalValidationRules(proposal) : draft.validationRules,

    bundleMandatory: hasSignals ? proposal.bundle_mandatory : draft.bundleMandatory,

    bundleConditional: hasSignals ? proposal.bundle_conditional : draft.bundleConditional,

    extractionFields: normalizeExtractionFieldKeys(proposal.extraction_fields),

    requiredFields: normalizeExtractionFieldKeys(proposal.required_fields),

    absentFields: normalizeExtractionFieldKeys(proposal.absent_fields),

    classifier: {

      ...classifier,

      enabled: hasSignals ? true : classifier.enabled,

      confidence: hasSignals ? 0.8 : classifier.confidence,

    },

    classifierCustomized: false,

    minRouteConfidence: hasSignals ? proposal.min_route_confidence : draft.minRouteConfidence,

    matrixTemplateCode:
      resolvedTemplateId !== "custom" ? resolvedTemplateId : draft.matrixTemplateCode,

  };

}



export function formatProposalSummary(proposal: DocumentTypeSampleProposal): Array<{

  label: string;

  value: string;

}> {

  return [

    {

      label: "Proposal source",

      value: proposal.proposal_source ?? "heuristic",

    },

    {

      label: "Recognition signals",

      value: proposal.recognition_signals.length

        ? proposal.recognition_signals.join(", ")

        : "None detected",

    },

    {

      label: "Extraction fields",

      value: proposal.extraction_fields.length

        ? proposal.extraction_fields.map((key) => extractionFieldLabel(key)).join(", ")

        : "None",

    },

    {

      label: "Required fields",

      value: proposal.required_fields.length

        ? proposal.required_fields.map((key) => extractionFieldLabel(key)).join(", ")

        : "None",

    },

    {

      label: "Must be absent",

      value: proposal.absent_fields.length

        ? proposal.absent_fields.map((key) => extractionFieldLabel(key)).join(", ")

        : "None",

    },

  ];

}



export async function analyzeDocumentTypeSamples(

  files: File[],

  options?: { purchaseBundleRole?: string; draft?: DocumentTypeDefinition }

): Promise<DocumentTypeSampleProposal> {

  const fd = new FormData();

  for (const file of files) {

    fd.append("files", file);

  }

  if (options?.purchaseBundleRole) {

    fd.append("purchase_bundle_role", options.purchaseBundleRole);

  }

  if (options?.draft?.code) {

    fd.append("expected_document_type_code", options.draft.code);

    fd.append("draft_document_type_json", JSON.stringify(options.draft));

  }

  return api.analyzeDocumentTypeSamples(fd, {
    timeoutMs: Math.min(600_000, 90_000 + files.length * 60_000),
  });
}



export function analyzeSamplesErrorMessage(err: unknown): string {

  if (err instanceof ApiError) {

    if (err.status === 403) {

      return "You need the Edit Policy permission to analyze samples.";

    }

    if (err.status === 408) {

      return err.message;

    }

    if (err.status === 413) {

      return "One or more files are too large (max 25 MB each).";

    }

    return err.message;

  }

  if (err instanceof TypeError && /fetch|network/i.test(String(err.message))) {

    return "Network error — check the API is running and try fewer files.";

  }

  return err instanceof Error ? err.message : "Analysis failed";

}

