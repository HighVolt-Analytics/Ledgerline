/**

 * Sample-file analysis for document type cards (Rule Book editor).

 */



import type { RecognitionSignalId } from "@/lib/documentClassifierBuilder";

import {

  buildClassifierFromSignals,

  type ClassifierLayout,

} from "@/lib/documentClassifierBuilder";

import { getDocumentTypeTemplate, type DocumentTypeTemplateId } from "@/lib/documentTypeTemplates";

import {

  approvalModeLabel,

  matchModeLabel,

  playbookProfileLabel,

  type ApprovalMode,

  type MatchMode,

  type PlaybookProfile,

} from "@/lib/documentPlaybookConfig";

import {

  normalizeValidationRules,

  validationCheckLabel,

  type ValidationRuleConfig,

} from "@/lib/documentValidationChecks";

import { normalizeExtractionFieldKeys, extractionFieldLabel } from "@/lib/documentExtractionFields";

import type { DocumentTypeClass, DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

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



function normalizeSignals(values: string[]): RecognitionSignalId[] {

  return values.filter((id): id is RecognitionSignalId => RECOGNITION_SIGNALS.has(id));

}



function mapValidationRules(rules: ValidationRuleProposal[]): ValidationRuleConfig[] {

  return normalizeValidationRules(

    rules.map((row) => ({

      code: row.code,

      enabled: row.enabled,

      severity: row.severity,

    }))

  );

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



  const playbookProfile = (proposal.playbook_profile || draft.playbookProfile) as PlaybookProfile;

  const validationRules =

    proposal.validation_rules.length > 0

      ? mapValidationRules(proposal.validation_rules)

      : draft.validationRules;



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

    oneLine: proposal.one_line.trim() || draft.oneLine,

    klass: (proposal.klass || draft.klass) as DocumentTypeClass,

    posting: proposal.posting || draft.posting,

    routeTarget: proposal.route_target || draft.routeTarget,

    extractionFields: normalizeExtractionFieldKeys(proposal.extraction_fields),

    requiredFields: normalizeExtractionFieldKeys(proposal.required_fields),

    absentFields: normalizeExtractionFieldKeys(proposal.absent_fields),

    playbookProfile,

    matchPolicy: { mode: proposal.match_mode || draft.matchPolicy?.mode || "none" },

    approvalPolicy: {

      mode: proposal.approval_mode || draft.approvalPolicy?.mode || "touchless_on_clean_match",

    },

    purchaseBundleRole: (proposal.purchase_bundle_role ||

      draft.purchaseBundleRole) as DocumentTypeDefinition["purchaseBundleRole"],

    validationProfile: proposal.validation_profile || draft.validationProfile,

    validationRules,

    bundleMandatory: proposal.bundle_mandatory.length

      ? [...proposal.bundle_mandatory]

      : draft.bundleMandatory,

    bundleConditional: proposal.bundle_conditional.length

      ? [...proposal.bundle_conditional]

      : draft.bundleConditional,

    minRouteConfidence: proposal.min_route_confidence ?? draft.minRouteConfidence,

    classifier: {

      ...classifier,

      enabled: signalIds.length > 0 ? true : classifier.enabled,

    },

    classifierCustomized: false,

  };

}



export function formatProposalSummary(proposal: DocumentTypeSampleProposal): Array<{

  label: string;

  value: string;

}> {

  const enabledChecks = proposal.validation_rules

    .filter((row) => row.enabled)

    .map((row) => validationCheckLabel(row.code))

    .join(", ");



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

    { label: "Summary", value: proposal.one_line || "—" },

    { label: "Class", value: proposal.klass },

    { label: "Posting", value: proposal.posting },

    { label: "Route", value: proposal.route_target },

    {

      label: "Playbook",

      value: playbookProfileLabel(proposal.playbook_profile as PlaybookProfile),

    },

    {

      label: "Match",

      value: matchModeLabel(proposal.match_mode),

    },

    {

      label: "Approval",

      value: approvalModeLabel(proposal.approval_mode),

    },

    {

      label: "Bundle required",

      value: proposal.bundle_mandatory.length ? proposal.bundle_mandatory.join(", ") : "None",

    },

    {

      label: "Bundle advisory",

      value: proposal.bundle_conditional.length ? proposal.bundle_conditional.join(", ") : "None",

    },

    {

      label: "Validation checks",

      value: enabledChecks || "None",

    },

    {

      label: "Min route confidence",

      value: `${Math.round(proposal.min_route_confidence * 100)}%`,

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

