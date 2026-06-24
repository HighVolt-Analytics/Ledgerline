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

import type { ApprovalMode, MatchMode } from "@/lib/documentPlaybookConfig";

import type {
  DocumentTypeDefinition,
  DocumentTypeSampleAnalysis,
} from "@/lib/v5DocumentTypes";

import { api, ApiError } from "@/api/client";



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

};



export type ValidationRuleProposal = {

  code: string;

  enabled: boolean;

  severity: "block" | "warn";

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

};



const RECOGNITION_SIGNALS = new Set<string>([

  "heading_po",

  "text_po",

  "filename_po",

  "heading_grn",

  "text_grn",

  "filename_grn",

  "heading_contract",

  "text_contract",

  "filename_contract",

  "text_terms",

  "text_governing_law",

  "text_signed_behalf",

  "heading_invoice",

  "text_invoice",

  "filename_invoice",

  "text_credit_note",

  "filename_credit_note",

  "text_debit_note",

  "filename_debit_note",

  "text_proforma",

  "filename_proforma",

  "text_recurring",

  "filename_recurring",

  "text_utility",

  "filename_utility",

  "text_freight",

  "filename_freight",

  "text_import",

  "filename_import",

  "text_intercompany",

  "filename_intercompany",

  "text_claim",

  "filename_claim",

  "text_statement",

  "filename_statement",

  "text_timesheet",

  "filename_timesheet",

  "text_remittance",

  "filename_remittance",

  "text_rcti",

  "filename_rcti",

  "text_consignment",

  "filename_consignment",

  "text_dunning",

  "filename_dunning",

  "text_bank_change",

  "filename_bank_change",

  "text_quote",

  "filename_quote",

  "text_tax_notice",

  "filename_tax_notice",

  "channel_whatsapp",

  "has_po_reference",

  "has_invoice_number",

  "has_total_amount",

]);



export function buildSampleAnalysisRecord(
  filenames: string[],
  proposal: DocumentTypeSampleProposal
): DocumentTypeSampleAnalysis {
  return {
    analyzedAt: new Date().toISOString(),
    filenames,
    fileCount: filenames.length,
    recognitionSignals: proposal.recognition_signals ?? [],
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

  return values.filter((id): id is RecognitionSignalId => RECOGNITION_SIGNALS.has(id));

}



function isPlaceholderTitle(value: string): boolean {

  const token = value.trim().toLowerCase();

  return token === "new document type" || token === "new type";

}



export function mergeSampleProposalIntoDraft(

  draft: DocumentTypeDefinition,

  proposal: DocumentTypeSampleProposal,

  templateId: DocumentTypeTemplateId

): DocumentTypeDefinition {

  const template = getDocumentTypeTemplate(templateId);

  const signalIds = normalizeSignals(proposal.recognition_signals);

  const layout = proposal.classifier_layout ?? template.classifierLayout;



  const classifier =

    signalIds.length > 0

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

    extractionFields: normalizeExtractionFieldKeys(proposal.extraction_fields),

    requiredFields: normalizeExtractionFieldKeys(proposal.required_fields),

    absentFields: normalizeExtractionFieldKeys(proposal.absent_fields),

    classifier: {

      ...classifier,

      enabled: signalIds.length > 0 ? true : classifier.enabled,

      confidence: signalIds.length > 0 ? 0.8 : classifier.confidence,

    },

    classifierCustomized: false,

    minRouteConfidence:
      signalIds.length > 0
        ? Math.min(draft.minRouteConfidence, 0.55)
        : draft.minRouteConfidence,

  };

}



export function formatProposalSummary(proposal: DocumentTypeSampleProposal): Array<{

  label: string;

  value: string;

}> {

  return [

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

