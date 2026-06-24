/** Dossier hero view types — UI model until GET /api/dossiers ships. */

import type { DossierApprovalChain } from "@/lib/dossierApproval";
import type { DossierLinkedDocuments } from "@/lib/dossierLinkedDocuments";

export type { DossierApprovalChain, DossierApprovalStep } from "@/lib/dossierApproval";
export type {
  DossierLinkedDocument,
  DossierLinkedDocuments,
} from "@/lib/dossierLinkedDocuments";

/**
 * Stage order mirrors Ledgerline capture + `process_invoice`:
 * ingest → duplicate file hash → parse → classify → playbook → vendor hold →
 * validate → match → approve → map → journal → reconcile → process → pay → archive.
 */
export const DOSSIER_PIPELINE_PHASES = [
  { id: "capture", label: "Capture" },
  { id: "process", label: "Process" },
  { id: "approve_map", label: "Approve" },
  { id: "ledger", label: "Ledger" },
  { id: "finish", label: "Finish" },
] as const;

export type DossierPipelinePhaseId = (typeof DOSSIER_PIPELINE_PHASES)[number]["id"];

export const DOSSIER_PIPELINE_STAGES = [
  { id: "ingest", order: 1, label: "Ingest", phase: "capture" as const },
  { id: "duplicate", order: 2, label: "Duplicate file check", phase: "capture" as const },
  { id: "extract", order: 3, label: "Extract", phase: "capture" as const },
  { id: "classify", order: 4, label: "Classify", phase: "capture" as const },
  { id: "bundle", order: 5, label: "Bundle / Playbook", phase: "process" as const },
  { id: "vendor_hold", order: 6, label: "Vendor hold", phase: "process" as const },
  { id: "validate", order: 7, label: "Validate", phase: "process" as const },
  { id: "match", order: 8, label: "Match", phase: "process" as const },
  { id: "approve", order: 9, label: "Approve", phase: "approve_map" as const },
  { id: "map_gl", order: 10, label: "Map GL", phase: "approve_map" as const },
  { id: "journal", order: 11, label: "Journal", phase: "ledger" as const },
  { id: "reconcile", order: 12, label: "Reconcile", phase: "ledger" as const },
  { id: "post", order: 13, label: "Process", phase: "ledger" as const },
  { id: "pay", order: 14, label: "Pay", phase: "finish" as const },
  { id: "archive", order: 15, label: "Archive", phase: "finish" as const },
] as const;

export type DossierPipelineStageId = (typeof DOSSIER_PIPELINE_STAGES)[number]["id"];

/** Wire-up reference: audit events and InvoiceStatus per stage. */
export const DOSSIER_PIPELINE_BACKEND_MAP: Record<
  DossierPipelineStageId,
  { auditEvents: string[]; invoiceStatus?: string }
> = {
  ingest: {
    auditEvents: ["email_ingested", "invoice_uploaded", "invoice_file_attached"],
  },
  duplicate: {
    auditEvents: [
      "duplicate_skipped",
      "duplicate_in_progress",
      "duplicate_reingest_rejected",
    ],
  },
  extract: {
    auditEvents: ["parse_completed", "invoice_parsed", "parsing_failed"],
    invoiceStatus: "parsing",
  },
  classify: {
    auditEvents: ["document_classified", "routing_review_required"],
  },
  bundle: { auditEvents: ["playbook_evaluated", "routing_review_required"] },
  vendor_hold: { auditEvents: ["vendor_registration_hold"] },
  validate: {
    auditEvents: ["validation_passed", "validation_failed"],
    invoiceStatus: "validating",
  },
  match: { auditEvents: ["three_way_match_evaluated", "purchase_variance_approved"] },
  approve: {
    auditEvents: ["invoice_approved", "approval_requested"],
  },
  map_gl: {
    auditEvents: ["mapping_applied", "mapping_review_required"],
    invoiceStatus: "mapping",
  },
  journal: { auditEvents: [], invoiceStatus: "journaling" },
  reconcile: {
    auditEvents: ["reconciliation_halted", "reconciliation_skipped"],
    invoiceStatus: "reconciling",
  },
  post: {
    auditEvents: ["invoice_processed", "invoice_published_to_ledger", "purchase_document_processed"],
    invoiceStatus: "processed",
  },
  pay: { auditEvents: [] },
  archive: { auditEvents: ["vault_stored"] },
};

export type DossierStageState = "pass" | "fail" | "waived" | "pending";

export type DossierOutcome =
  | "auto_posted"
  | "manual_posted"
  | "blocked"
  | "parked"
  | "in_progress";

export type DossierFraudRisk = "low" | "medium" | "high";

export type DossierPipelineCheckState = "pass" | "fail" | "waived" | "skipped" | "pending";

export type DossierPipelineCheck = {
  id: string;
  label: string;
  state: DossierPipelineCheckState;
  detail?: string;
  ruleRef?: string;
  expected?: string;
  actual?: string;
};

export type DossierPipelineEvidence = {
  label: string;
  ref: string;
};

export type DossierPipelineStep = {
  stageId: DossierPipelineStageId;
  state: DossierStageState;
  /** One-line stage outcome (audit log headline). */
  detail: string;
  at: string | null;
  actor?: string;
  durationMs?: number;
  exceptionCode?: string | null;
  failureReason?: string | null;
  remediation?: string | null;
  /** Why this stage did not run (downstream of an earlier fail). */
  blockedReason?: string | null;
  checks?: DossierPipelineCheck[];
  evidence?: DossierPipelineEvidence[];
};

export type DossierSummary = {
  id: string;
  invoiceId?: number;
  documentTypeCode: string;
  documentTypeTitle: string;
  vendor: string;
  buyer: string;
  invoiceRef: string;
  captureChannel: string;
  invoiceDate: string;
  currency: string;
  subtotal: number;
  tax: number;
  total: number;
  classificationLabel: string;
  classificationConfidence: number;
  fraudRisk: DossierFraudRisk;
  poReference: string | null;
  slaLabel: string;
  slaBreached?: boolean;
  owner: string;
  outcome: DossierOutcome;
  outcomeBanner: string;
  pipeline: DossierPipelineStep[];
  linkedDocuments: DossierLinkedDocuments;
  approvalChain: DossierApprovalChain;
};

/** Demo-only IDs from dossiersMockData (DOS-0401 … DOS-0410) — not in the API. */
export function isLegacyMockDossierId(id: string): boolean {
  return /^DOS-\d{4}$/i.test(id.trim());
}

export function pipelineStageSummary(pipeline: DossierPipelineStep[]): string {
  const evaluated = pipeline.filter((step) => step.state !== "pending");
  const pass = evaluated.filter((step) => step.state === "pass").length;
  const fail = evaluated.filter((step) => step.state === "fail").length;
  const waived = evaluated.filter((step) => step.state === "waived").length;
  if (fail > 0) return `${pass} pass · ${fail} fail`;
  if (waived > 0) return `${pass} pass · ${waived} waived`;
  if (evaluated.length === DOSSIER_PIPELINE_STAGES.length) return `${pass} pass`;
  return `${pass} pass · ${evaluated.length}/${DOSSIER_PIPELINE_STAGES.length}`;
}

export function dossierOutcomeLabel(outcome: DossierOutcome): string {
  if (outcome === "auto_posted") return "Auto-posted";
  if (outcome === "manual_posted") return "Manual post";
  if (outcome === "blocked") return "Blocked";
  if (outcome === "parked") return "Parked";
  return "In progress";
}

export function dossierPipelineCounts(pipeline: DossierPipelineStep[]): {
  pass: number;
  fail: number;
  waived: number;
} {
  const evaluated = pipeline.filter((step) => step.state !== "pending");
  return {
    pass: evaluated.filter((step) => step.state === "pass").length,
    fail: evaluated.filter((step) => step.state === "fail").length,
    waived: evaluated.filter((step) => step.state === "waived").length,
  };
}

function rollupPhaseState(states: DossierStageState[]): DossierStageState {
  if (states.some((s) => s === "fail")) return "fail";
  if (states.every((s) => s === "pass" || s === "waived")) {
    return states.some((s) => s === "waived") ? "waived" : "pass";
  }
  if (states.every((s) => s === "pending")) return "pending";
  return "pending";
}

export type DossierPipelinePhaseSummary = {
  phaseId: DossierPipelinePhaseId;
  label: string;
  state: DossierStageState;
};

/** Roll 15 stages into 5 phase dots for list cards. */
export function dossierPipelinePhases(pipeline: DossierPipelineStep[]): DossierPipelinePhaseSummary[] {
  const byStage = new Map(pipeline.map((step) => [step.stageId, step.state]));
  return DOSSIER_PIPELINE_PHASES.map((phase) => {
    const stageIds = DOSSIER_PIPELINE_STAGES.filter((s) => s.phase === phase.id).map((s) => s.id);
    const states = stageIds.map((id) => byStage.get(id) ?? "pending");
    return { phaseId: phase.id, label: phase.label, state: rollupPhaseState(states) };
  });
}

export function isStageBlocked(step: DossierPipelineStep | undefined): boolean {
  return (
    step?.state === "pending" &&
    Boolean(step.blockedReason?.startsWith("Blocked —"))
  );
}

export function stageShouldDefaultOpen(
  step: DossierPipelineStep | undefined,
  blocked: boolean
): boolean {
  if (!step) return false;
  if (step.state === "fail" || step.state === "waived") return true;
  if (blocked) return true;
  if (step.state === "pending" && step.detail && step.detail !== "—") return true;
  return false;
}

export function dossierStageLabel(stageId: DossierPipelineStageId): string {
  return DOSSIER_PIPELINE_STAGES.find((stage) => stage.id === stageId)?.label ?? stageId;
}

export function firstPipelineFailure(
  pipeline: DossierPipelineStep[]
): DossierPipelineStep | undefined {
  const byStage = new Map(pipeline.map((step) => [step.stageId, step]));
  for (const stage of DOSSIER_PIPELINE_STAGES) {
    const step = byStage.get(stage.id);
    if (step?.state === "fail") return step;
  }
  return undefined;
}

export function pipelineBlockedFromStageId(
  pipeline: DossierPipelineStep[],
  stageId: DossierPipelineStageId
): boolean {
  const fail = firstPipelineFailure(pipeline);
  if (!fail) return false;
  const failOrder =
    DOSSIER_PIPELINE_STAGES.find((stage) => stage.id === fail.stageId)?.order ?? 0;
  const stageOrder =
    DOSSIER_PIPELINE_STAGES.find((stage) => stage.id === stageId)?.order ?? 0;
  return stageOrder > failOrder;
}

export function dossierStageDescription(stageId: DossierPipelineStageId): string {
  const descriptions: Record<DossierPipelineStageId, string> = {
    ingest: "Document received and stored.",
    duplicate: "Checked for duplicate uploads.",
    extract: "Fields extracted from the file.",
    classify: "Document type assigned from the rule book.",
    bundle: "Required supporting documents checked.",
    vendor_hold: "Vendor registration status verified.",
    validate: "Business rules and validation checks run.",
    match: "PO, GRN, and invoice amounts compared.",
    approve: "Approval policy applied.",
    map_gl: "General ledger account assigned.",
    journal: "Journal entries generated.",
    reconcile: "Sub-ledger reconciliation run.",
    post: "Posted to the ledger.",
    pay: "Payment queue prepared.",
    archive: "Archived for retention.",
  };
  return descriptions[stageId];
}
