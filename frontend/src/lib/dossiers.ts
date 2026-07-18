/** Dossier hero view types — aligned with GET /api/dossiers. */

import type { DossierApprovalChain } from "@/lib/dossierApproval";
import type { DossierLinkedDocuments } from "@/lib/dossierLinkedDocuments";
import { ROUTE_SALES } from "@/lib/invoice";

export type { DossierApprovalChain, DossierApprovalStep } from "@/lib/dossierApproval";
export type {
  DossierLinkedDocument,
  DossierLinkedDocuments,
} from "@/lib/dossierLinkedDocuments";

/**
 * Stage order mirrors `process_invoice` (Storage → OCR → quality → LLM → gate → extract → DT → …).
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
  { id: "duplicate", order: 2, label: "Duplicate check", phase: "capture" as const },
  { id: "storage", order: 3, label: "Storage", phase: "capture" as const },
  { id: "ocr", order: 4, label: "OCR", phase: "capture" as const },
  { id: "quality", order: 5, label: "Image quality", phase: "capture" as const },
  { id: "llm_classify", order: 6, label: "LLM classify", phase: "capture" as const },
  { id: "confidence_gate", order: 7, label: "Confidence gate", phase: "capture" as const },
  { id: "extract", order: 8, label: "Field extract", phase: "capture" as const },
  { id: "document_type", order: 9, label: "Document type", phase: "capture" as const },
  { id: "bundle", order: 10, label: "Supporting documents", phase: "process" as const },
  { id: "vendor_hold", order: 11, label: "Master hold", phase: "process" as const },
  { id: "validate", order: 12, label: "Validate", phase: "process" as const },
  { id: "match", order: 13, label: "Match", phase: "process" as const },
  { id: "approve", order: 14, label: "Approve", phase: "approve_map" as const },
  { id: "map_gl", order: 15, label: "Map GL", phase: "approve_map" as const },
  { id: "journal", order: 16, label: "Journal", phase: "ledger" as const },
  { id: "reconcile", order: 17, label: "Reconcile", phase: "ledger" as const },
  { id: "post", order: 18, label: "Post", phase: "ledger" as const },
  { id: "pay", order: 19, label: "Pay", phase: "finish" as const },
  { id: "archive", order: 20, label: "Archive", phase: "finish" as const },
] as const;

/** Vision understood path — same points as the Audit Processing tab. */
export const UNDERSTOOD_PIPELINE_STAGES = [
  { id: "ingest", order: 1, label: "Received", phase: "capture" as const },
  { id: "duplicate", order: 2, label: "Duplicate check", phase: "capture" as const },
  { id: "storage", order: 3, label: "Storage", phase: "capture" as const },
  { id: "file_validity", order: 4, label: "File validity", phase: "capture" as const },
  { id: "vision_understand", order: 5, label: "Vision understand", phase: "capture" as const },
  { id: "extract", order: 6, label: "Vision header", phase: "capture" as const },
  { id: "bundle", order: 7, label: "Bundle", phase: "process" as const },
  { id: "archive", order: 8, label: "Vault", phase: "finish" as const },
] as const;

export type DossierPipelineStageId =
  | (typeof DOSSIER_PIPELINE_STAGES)[number]["id"]
  | (typeof UNDERSTOOD_PIPELINE_STAGES)[number]["id"];

/** Vision understood path — capture header, soft-bundle, vault only. */
export const UNDERSTOOD_DOSSIER_STAGE_IDS: ReadonlySet<string> = new Set(
  UNDERSTOOD_PIPELINE_STAGES.map((stage) => stage.id)
);

export type DossierPipelinePath = "understood" | "not_understood" | "unknown";

export function pipelineStageCatalog(
  path: DossierPipelinePath | null | undefined
): readonly {
  id: DossierPipelineStageId;
  order: number;
  label: string;
  phase: DossierPipelinePhaseId;
}[] {
  return path === "understood" ? UNDERSTOOD_PIPELINE_STAGES : DOSSIER_PIPELINE_STAGES;
}

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
  storage: {
    auditEvents: ["storage_verified"],
  },
  file_validity: {
    auditEvents: ["file_validity_passed", "file_validity_failed"],
  },
  vision_understand: {
    auditEvents: ["vision_understand_passed", "vision_understand_failed"],
  },
  ocr: {
    auditEvents: ["ocr_completed", "parsing_failed"],
    invoiceStatus: "parsing",
  },
  quality: {
    auditEvents: ["image_quality_gate_passed", "image_quality_gate_failed"],
  },
  llm_classify: {
    auditEvents: [
      "llm_classified",
      "vendor_classification_drift",
      "vendor_classification_baseline",
    ],
  },
  confidence_gate: {
    auditEvents: [
      "classification_gate_passed",
      "classification_gate_failed",
      "routing_review_required",
    ],
  },
  extract: {
    auditEvents: [
      "vision_header_extracted",
      "parse_completed",
      "invoice_parsed",
      "field_confidence_evaluated",
    ],
    invoiceStatus: "parsing",
  },
  document_type: {
    auditEvents: ["document_classified", "classification_resolved"],
  },
  bundle: {
    auditEvents: [
      "vision_bundle_linked",
      "vision_bundle_standalone",
      "playbook_evaluated",
      "routing_review_required",
    ],
  },
  vendor_hold: {
    auditEvents: [
      "vendor_registration_hold",
      "vendor_registration_cleared",
      "vendor_registration_waived",
      "vendor_registration_released",
      "customer_registration_hold",
      "customer_registration_cleared",
      "customer_registration_waived",
    ],
  },
  validate: {
    auditEvents: [
      "validation_passed",
      "validation_failed",
      "validation_bypassed_after_human_approval",
    ],
    invoiceStatus: "validating",
  },
  match: {
    auditEvents: [
      "three_way_match_evaluated",
      "match_phase_evaluated",
      "match_context_incomplete",
      "purchase_variance_approved",
    ],
  },
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
  archive: {
    auditEvents: [
      "vault_stored",
      "blob_relocated",
      "vault_layout_sync_skipped",
      "vision_path_pending",
    ],
  },
};

export type DossierStageState = "pass" | "fail" | "waived" | "skipped" | "pending";

export type DossierOutcome =
  | "auto_posted"
  | "manual_posted"
  | "blocked"
  | "parked"
  | "vaulted"
  | "in_progress";

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

/** Show only stages for the path this document actually ran. */
export function filterDossierPipelineForPath(
  pipeline: DossierPipelineStep[],
  path: DossierPipelinePath | null | undefined
): DossierPipelineStep[] {
  const resolved = resolveDossierPipelinePath(pipeline, path);
  if (resolved !== "understood") return pipeline;
  return pipeline.filter((step) => UNDERSTOOD_DOSSIER_STAGE_IDS.has(step.stageId));
}

/** Prefer API path; infer understood when stages were marked skipped for that path. */
export function resolveDossierPipelinePath(
  pipeline: DossierPipelineStep[],
  path: DossierPipelinePath | null | undefined
): DossierPipelinePath {
  if (path === "understood" || path === "not_understood") return path;
  const understoodSkip = pipeline.some(
    (step) =>
      (step.state === "skipped" || step.state === "waived") &&
      (step.detail || "").toLowerCase().includes("understood path")
  );
  if (understoodSkip) return "understood";
  const onlyUnderstoodStages =
    pipeline.length > 0 &&
    pipeline.every((step) => UNDERSTOOD_DOSSIER_STAGE_IDS.has(step.stageId));
  if (onlyUnderstoodStages && pipeline.length <= UNDERSTOOD_DOSSIER_STAGE_IDS.size) {
    return "understood";
  }
  return path ?? "unknown";
}

export type DossierSummary = {
  id: string;
  invoiceId?: number;
  documentTypeCode: string;
  documentTypeTitle: string;
  vendor: string;
  counterpartyLabel?: string;
  routeTarget?: string | null;
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
  poReference: string | null;
  soReference?: string | null;
  linkageReference?: string | null;
  slaLabel: string;
  slaBreached?: boolean;
  owner: string;
  outcome: DossierOutcome;
  outcomeBanner: string;
  blockerStageId?: DossierPipelineStageId | null;
  blockerReason?: string | null;
  blockerRemediation?: string | null;
  pipelinePath?: DossierPipelinePath;
  pipeline: DossierPipelineStep[];
  linkedDocuments: DossierLinkedDocuments;
  approvalChain: DossierApprovalChain;
};

/** Demo-only IDs from dossiersMockData (DOS-0401 … DOS-0410) — not in the API. */
export function isLegacyMockDossierId(id: string): boolean {
  return /^DOS-\d{4}$/i.test(id.trim());
}

export function dossierStageStateLabel(state: DossierStageState): string {
  if (state === "pass") return "Complete";
  if (state === "fail") return "Failed";
  if (state === "waived" || state === "skipped") return "Skipped";
  return "Waiting";
}

export function firstPipelineFailure(
  pipeline: DossierPipelineStep[]
): DossierPipelineStep | undefined {
  const byStage = new Map(pipeline.map((step) => [step.stageId, step]));
  for (const stage of stagesForPipeline(pipeline)) {
    const step = byStage.get(stage.id);
    if (step?.state === "fail") return step;
  }
  return undefined;
}

/** First pending stage that is blocking forward progress. */
export function firstPipelineBottleneck(
  pipeline: DossierPipelineStep[]
): { stageId: DossierPipelineStageId; step: DossierPipelineStep } | undefined {
  const fail = firstPipelineFailure(pipeline);
  if (fail) return { stageId: fail.stageId, step: fail };

  const byStage = new Map(pipeline.map((step) => [step.stageId, step]));
  for (const stage of stagesForPipeline(pipeline)) {
    const step = byStage.get(stage.id);
    if (!step) continue;
    if (step.state === "skipped" || step.state === "waived") continue;
    if (step.state === "pending" && step.detail && step.detail !== "—") {
      return { stageId: stage.id, step };
    }
    if (step.state === "pending") {
      return { stageId: stage.id, step };
    }
  }
  return undefined;
}

function stagesForPipeline(pipeline: DossierPipelineStep[]) {
  const byStage = new Map(pipeline.map((step) => [step.stageId, step]));
  const understoodOnly =
    pipeline.length > 0 &&
    pipeline.every((step) => UNDERSTOOD_DOSSIER_STAGE_IDS.has(step.stageId));
  const catalog = understoodOnly ? UNDERSTOOD_PIPELINE_STAGES : DOSSIER_PIPELINE_STAGES;
  return catalog.filter((stage) => byStage.has(stage.id));
}

export function pipelineActiveStage(
  pipeline: DossierPipelineStep[]
): { stageId: DossierPipelineStageId; step: DossierPipelineStep } | undefined {
  const bottleneck = firstPipelineBottleneck(pipeline);
  if (bottleneck) return bottleneck;

  const byStage = new Map(pipeline.map((step) => [step.stageId, step]));
  const ordered = DOSSIER_PIPELINE_STAGES.filter((stage) => byStage.has(stage.id));
  let last: { stageId: DossierPipelineStageId; step: DossierPipelineStep } | undefined;
  for (const stage of ordered) {
    const step = byStage.get(stage.id);
    if (!step) continue;
    if (step.state === "pass" || step.state === "waived") {
      last = { stageId: stage.id, step };
    }
  }
  return last;
}

export function pipelineProgressSummary(
  pipeline: DossierPipelineStep[],
  routeTarget?: string | null
): string {
  const complete = pipeline.filter(
    (step) => step.state === "pass" || step.state === "waived" || step.state === "skipped"
  ).length;
  const total = pipeline.length || DOSSIER_PIPELINE_STAGES.length;
  const fail = firstPipelineFailure(pipeline);
  if (fail) {
    return `${complete} of ${total} complete · failed at ${dossierStageLabel(fail.stageId, routeTarget)}`;
  }
  return `${complete} of ${total} complete`;
}

export function dossierBlockerFromSummary(dossier: Pick<
  DossierSummary,
  "pipeline" | "blockerStageId" | "blockerReason" | "blockerRemediation" | "outcome" | "outcomeBanner"
>): {
  stageId: DossierPipelineStageId;
  reason: string;
  remediation?: string | null;
  exceptionCode?: string | null;
  step: DossierPipelineStep;
} | undefined {
  const fail = firstPipelineFailure(dossier.pipeline);
  if (fail) {
    const reason =
      dossier.blockerReason?.trim() ||
      fail.failureReason?.trim() ||
      (fail.detail !== "—" ? fail.detail : "") ||
      "This stage did not pass.";
    return {
      stageId: (dossier.blockerStageId as DossierPipelineStageId | undefined) ?? fail.stageId,
      reason,
      remediation: dossier.blockerRemediation ?? fail.remediation,
      exceptionCode: fail.exceptionCode,
      step: fail,
    };
  }

  if (dossier.outcome === "blocked") {
    const bottleneck = firstPipelineBottleneck(dossier.pipeline);
    const reason =
      dossier.blockerReason?.trim() ||
      dossier.outcomeBanner?.trim() ||
      bottleneck?.step.detail?.trim() ||
      "Pipeline blocked — review required";
    if (bottleneck) {
      return {
        stageId:
          (dossier.blockerStageId as DossierPipelineStageId | undefined) ??
          bottleneck.stageId,
        reason,
        remediation: dossier.blockerRemediation,
        exceptionCode: bottleneck.step.exceptionCode,
        step: bottleneck.step,
      };
    }
    return {
      stageId: "validate",
      reason,
      remediation: dossier.blockerRemediation,
      exceptionCode: null,
      step: {
        stageId: "validate",
        state: "pending",
        detail: reason,
        at: null,
      },
    };
  }

  return undefined;
}

export function stageIdsForPhase(phaseId: DossierPipelinePhaseId): DossierPipelineStageId[] {
  return DOSSIER_PIPELINE_STAGES.filter((stage) => stage.phase === phaseId).map((stage) => stage.id);
}

export function phaseIdForStage(stageId: DossierPipelineStageId): DossierPipelinePhaseId {
  return (
    UNDERSTOOD_PIPELINE_STAGES.find((stage) => stage.id === stageId)?.phase ??
    DOSSIER_PIPELINE_STAGES.find((stage) => stage.id === stageId)?.phase ??
    "capture"
  );
}

export function defaultActivePipelinePhase(pipeline: DossierPipelineStep[]): DossierPipelinePhaseId {
  const fail = firstPipelineFailure(pipeline);
  if (fail) return phaseIdForStage(fail.stageId);

  for (const phase of DOSSIER_PIPELINE_PHASES) {
    const steps = stageIdsForPhase(phase.id)
      .map((id) => pipeline.find((step) => step.stageId === id))
      .filter(Boolean) as DossierPipelineStep[];
    if (steps.some((step) => step.state === "fail" || step.state === "pending")) {
      return phase.id;
    }
  }

  return "capture";
}

export function phaseStageSummary(
  pipeline: DossierPipelineStep[],
  phaseId: DossierPipelinePhaseId,
  routeTarget?: string | null
): string {
  const byStage = new Map(pipeline.map((step) => [step.stageId, step]));
  const ids = stagesForPipeline(pipeline)
    .filter((stage) => stage.phase === phaseId && byStage.has(stage.id))
    .map((stage) => stage.id);
  const steps = ids.map((id) => byStage.get(id)).filter(Boolean) as DossierPipelineStep[];
  const complete = steps.filter(
    (step) => step.state === "pass" || step.state === "waived" || step.state === "skipped"
  ).length;
  const failed = steps.find((step) => step.state === "fail");
  if (failed) {
    return `Failed at ${dossierStageLabel(failed.stageId, routeTarget)}`;
  }
  return `${complete}/${ids.length || steps.length} complete`;
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
  if (outcome === "vaulted") return "Vaulted";
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
  if (states.every((s) => s === "pass")) return "pass";
  if (states.every((s) => s === "pass" || s === "waived" || s === "skipped")) {
    // Prefer Complete when any stage passed; Skipped only if nothing ran.
    if (states.some((s) => s === "pass")) return "pass";
    return "waived";
  }
  if (states.every((s) => s === "pending")) return "pending";
  return "pending";
}

export type DossierPipelinePhaseSummary = {
  phaseId: DossierPipelinePhaseId;
  label: string;
  state: DossierStageState;
};

/** Roll capture/process stages into 5 phase dots for list cards. */
export function dossierPipelinePhases(pipeline: DossierPipelineStep[]): DossierPipelinePhaseSummary[] {
  const byStage = new Map(pipeline.map((step) => [step.stageId, step.state]));
  const presentIds = new Set(pipeline.map((step) => step.stageId));
  const catalog = stagesForPipeline(pipeline);
  return DOSSIER_PIPELINE_PHASES.map((phase) => {
    const stageIds = catalog
      .filter((s) => s.phase === phase.id && presentIds.has(s.id))
      .map((s) => s.id);
    if (stageIds.length === 0) {
      return { phaseId: phase.id, label: phase.label, state: "waived" as const };
    }
    const states = stageIds.map((id) => byStage.get(id) ?? "pending");
    return { phaseId: phase.id, label: phase.label, state: rollupPhaseState(states) };
  }).filter((phase) => {
    const stageIds = catalog.filter(
      (s) => s.phase === phase.phaseId && presentIds.has(s.id)
    );
    return stageIds.length > 0;
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

export function dossierStageLabel(
  stageId: DossierPipelineStageId,
  routeTarget?: string | null,
): string {
  if (stageId === "vendor_hold" && routeTarget === ROUTE_SALES) {
    return "Customer hold";
  }
  return (
    UNDERSTOOD_PIPELINE_STAGES.find((stage) => stage.id === stageId)?.label ??
    DOSSIER_PIPELINE_STAGES.find((stage) => stage.id === stageId)?.label ??
    stageId
  );
}

export function pipelineBlockedFromStageId(
  pipeline: DossierPipelineStep[],
  stageId: DossierPipelineStageId
): boolean {
  const byStage = new Map(pipeline.map((step) => [step.stageId, step]));
  const step = byStage.get(stageId);
  if (isStageBlocked(step)) {
    return true;
  }

  const fail = firstPipelineFailure(pipeline);
  if (fail) {
    const failOrder =
      DOSSIER_PIPELINE_STAGES.find((stage) => stage.id === fail.stageId)?.order ?? 0;
    const stageOrder =
      DOSSIER_PIPELINE_STAGES.find((stage) => stage.id === stageId)?.order ?? 0;
    return stageOrder > failOrder;
  }

  const bottleneck = firstPipelineBottleneck(pipeline);
  if (!bottleneck) return false;
  const bottleneckOrder =
    DOSSIER_PIPELINE_STAGES.find((stage) => stage.id === bottleneck.stageId)?.order ?? 0;
  const stageOrder =
    DOSSIER_PIPELINE_STAGES.find((stage) => stage.id === stageId)?.order ?? 0;
  return stageOrder > bottleneckOrder;
}

export function dossierStageDescription(stageId: DossierPipelineStageId): string {
  const descriptions: Record<DossierPipelineStageId, string> = {
    ingest: "Document received and stored.",
    duplicate: "Checked for duplicate uploads.",
    storage: "Stored file verified before processing.",
    file_validity: "File type and readability checked.",
    vision_understand: "Vision model decided the document can be understood.",
    ocr: "Layout and text read from the document.",
    quality: "Image quality and OCR readability gate.",
    llm_classify: "LLM suggests document type from OCR.",
    confidence_gate: "Auto-route confidence and catalogue gate.",
    extract: "Header fields captured from vision understanding.",
    document_type: "Confirmed document type applied to the invoice.",
    bundle: "Soft-bundled with linked supporting documents.",
    vendor_hold: "Vendor registration status verified.",
    validate: "Business rules and validation checks run.",
    match: "PO, GRN, and invoice amounts compared.",
    approve: "Approval policy applied.",
    map_gl: "General ledger account assigned.",
    journal: "Journal entries generated.",
    reconcile: "Sub-ledger reconciliation run.",
    post: "Posted to the ledger.",
    pay: "Payment queue prepared.",
    archive: "Stored in the document vault.",
  };
  return descriptions[stageId];
}
