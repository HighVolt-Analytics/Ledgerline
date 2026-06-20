import type {
  DossierApprovalChain,
  DossierApprovalStep,
  DossierLinkedDocument,
  DossierLinkedDocuments,
  DossierOutcome,
  DossierPipelineStageId,
  DossierPipelineStep,
  DossierSummary,
} from "@/lib/dossiers";
import { DOSSIER_PIPELINE_STAGES } from "@/lib/dossiers";
import type { ApprovalMode } from "@/lib/documentPlaybookConfig";
import { api, ApiError } from "@/api/client";

export type DossierPipelineCheckApi = {
  id: string;
  label: string;
  state: string;
  detail?: string | null;
  rule_ref?: string | null;
  expected?: string | null;
  actual?: string | null;
};

export type DossierPipelineStepApi = {
  stage_id: string;
  state: string;
  detail: string;
  at?: string | null;
  actor?: string | null;
  duration_ms?: number | null;
  exception_code?: string | null;
  failure_reason?: string | null;
  remediation?: string | null;
  blocked_reason?: string | null;
  checks?: DossierPipelineCheckApi[];
  evidence?: Array<{ label: string; ref: string }>;
};

export type DossierLinkedDocumentApi = {
  id: string;
  document_type_code: string;
  label: string;
  document_ref?: string | null;
  present: boolean;
  requirement: string;
  purchase_bundle_role?: string | null;
  source?: string | null;
  linked_dossier_id?: string | null;
  is_anchor?: boolean;
  has_file?: boolean;
  linkage_detail?: string | null;
};

export type DossierLinkedDocumentsApi = {
  linkage_kind: string;
  linkage_key?: string | null;
  linkage_label: string;
  enforce_bundle: boolean;
  conditional_advisories?: string[];
  documents: DossierLinkedDocumentApi[];
  match_summary?: {
    status: string;
    po_value: number;
    invoice_total: number;
    deviation: number;
    currency: string;
  } | null;
  purchase_order_id?: number | null;
};

export type DossierApprovalStepApi = {
  id: string;
  kind: string;
  label: string;
  role: string;
  actor: string;
  state: string;
  at?: string | null;
  detail?: string | null;
  policy_ref?: string | null;
  sod_note?: string | null;
};

export type DossierApprovalChainApi = {
  policy_mode: string;
  policy_label: string;
  steps: DossierApprovalStepApi[];
};

export type DossierSummaryApi = {
  id: string;
  invoice_id: number;
  document_type_code: string;
  document_type_title: string;
  vendor: string;
  buyer: string;
  invoice_ref: string;
  capture_channel: string;
  invoice_date: string;
  currency: string;
  subtotal: number;
  tax: number;
  total: number;
  classification_label: string;
  classification_confidence: number;
  fraud_risk: string;
  po_reference?: string | null;
  sla_label: string;
  sla_breached?: boolean;
  owner: string;
  outcome: string;
  outcome_banner: string;
  pipeline: DossierPipelineStepApi[];
  linked_documents: DossierLinkedDocumentsApi;
  approval_chain: DossierApprovalChainApi;
};

function normalizePipeline(steps: DossierPipelineStep[]): DossierPipelineStep[] {
  const byStage = new Map(steps.map((step) => [step.stageId, step]));
  return DOSSIER_PIPELINE_STAGES.map((stage) => {
    const hit = byStage.get(stage.id);
    if (hit) return hit;
    return {
      stageId: stage.id as DossierPipelineStageId,
      state: "pending" as const,
      detail: "—",
      at: null,
    };
  });
}

function mapPipelineStep(step: DossierPipelineStepApi): DossierPipelineStep {
  return {
    stageId: step.stage_id as DossierPipelineStep["stageId"],
    state: step.state as DossierPipelineStep["state"],
    detail: step.detail,
    at: step.at ?? null,
    actor: step.actor ?? undefined,
    durationMs: step.duration_ms ?? undefined,
    exceptionCode: step.exception_code ?? undefined,
    failureReason: step.failure_reason ?? undefined,
    remediation: step.remediation ?? undefined,
    blockedReason: step.blocked_reason ?? undefined,
    checks: step.checks?.map((check) => ({
      id: check.id,
      label: check.label,
      state: check.state as "pass" | "fail" | "skipped" | "pending",
      detail: check.detail ?? undefined,
      ruleRef: check.rule_ref ?? undefined,
      expected: check.expected ?? undefined,
      actual: check.actual ?? undefined,
    })),
    evidence: step.evidence?.map((item) => ({ label: item.label, ref: item.ref })),
  };
}

function mapLinkedDocument(doc: DossierLinkedDocumentApi): DossierLinkedDocument {
  return {
    id: doc.id,
    documentTypeCode: doc.document_type_code,
    label: doc.label,
    documentRef: doc.document_ref ?? null,
    present: doc.present,
    requirement: doc.requirement as DossierLinkedDocument["requirement"],
    purchaseBundleRole: (doc.purchase_bundle_role ?? undefined) as DossierLinkedDocument["purchaseBundleRole"],
    source: doc.source as DossierLinkedDocument["source"],
    linkedDossierId: doc.linked_dossier_id ?? null,
    isAnchor: doc.is_anchor,
    hasFile: doc.has_file,
    linkageDetail: doc.linkage_detail ?? undefined,
  };
}

function mapLinkedDocuments(linked: DossierLinkedDocumentsApi): DossierLinkedDocuments {
  return {
    linkageKind: linked.linkage_kind as DossierLinkedDocuments["linkageKind"],
    linkageKey: linked.linkage_key ?? null,
    linkageLabel: linked.linkage_label,
    enforceBundle: linked.enforce_bundle,
    conditionalAdvisories: linked.conditional_advisories ?? [],
    documents: linked.documents.map(mapLinkedDocument),
    matchSummary: linked.match_summary
      ? {
          status: linked.match_summary.status,
          poValue: linked.match_summary.po_value,
          invoiceTotal: linked.match_summary.invoice_total,
          deviation: linked.match_summary.deviation,
          currency: linked.match_summary.currency,
        }
      : undefined,
    purchaseOrderId: linked.purchase_order_id ?? null,
  };
}

function mapApprovalStep(step: DossierApprovalStepApi): DossierApprovalStep {
  return {
    id: step.id,
    kind: step.kind as DossierApprovalStep["kind"],
    label: step.label,
    role: step.role,
    actor: step.actor,
    state: step.state as DossierApprovalStep["state"],
    at: step.at ?? null,
    detail: step.detail ?? undefined,
    policyRef: step.policy_ref ?? undefined,
    sodNote: step.sod_note ?? undefined,
  };
}

function mapApprovalChain(chain: DossierApprovalChainApi): DossierApprovalChain {
  return {
    policyMode: chain.policy_mode as ApprovalMode,
    policyLabel: chain.policy_label,
    steps: chain.steps.map(mapApprovalStep),
  };
}

export function mapDossierFromApi(row: DossierSummaryApi): DossierSummary {
  return {
    id: row.id,
    documentTypeCode: row.document_type_code,
    documentTypeTitle: row.document_type_title,
    vendor: row.vendor,
    buyer: row.buyer,
    invoiceRef: row.invoice_ref,
    captureChannel: row.capture_channel,
    invoiceDate: row.invoice_date,
    currency: row.currency,
    subtotal: row.subtotal,
    tax: row.tax,
    total: row.total,
    classificationLabel: row.classification_label,
    classificationConfidence: row.classification_confidence,
    fraudRisk: row.fraud_risk as DossierSummary["fraudRisk"],
    poReference: row.po_reference ?? null,
    slaLabel: row.sla_label,
    slaBreached: row.sla_breached,
    owner: row.owner,
    outcome: row.outcome as DossierOutcome,
    outcomeBanner: row.outcome_banner,
    pipeline: normalizePipeline(row.pipeline.map(mapPipelineStep)),
    linkedDocuments: mapLinkedDocuments(row.linked_documents),
    approvalChain: mapApprovalChain(row.approval_chain),
  };
}

export type DossierSummaryWithInvoiceId = DossierSummary & { invoiceId: number };

export function mapDossierDetailFromApi(row: DossierSummaryApi): DossierSummaryWithInvoiceId {
  return { ...mapDossierFromApi(row), invoiceId: row.invoice_id };
}

const DEFAULT_PAGE_SIZE = "12";

export async function fetchDossiersPage(params: {
  page: number;
  pageSize?: number;
  documentTypeCode?: string;
  q?: string;
  fresh?: boolean;
}): Promise<{
  rows: DossierSummary[];
  total: number;
  pages: number;
  page: number;
}> {
  const query: Record<string, string> = {
    page: String(params.page),
    page_size: String(params.pageSize ?? Number(DEFAULT_PAGE_SIZE)),
  };
  if (params.documentTypeCode && params.documentTypeCode !== "all") {
    query.document_type_code = params.documentTypeCode;
  }
  if (params.q?.trim()) {
    query.q = params.q.trim();
  }
  const res = await api.listDossiersWithMeta(query, { fresh: params.fresh });
  return {
    rows: res.data.map(mapDossierFromApi),
    total: res.meta.total ?? res.data.length,
    pages: res.meta.pages ?? 1,
    page: res.meta.page ?? params.page,
  };
}

export async function fetchDossierById(
  dossierId: string,
  options?: { fresh?: boolean }
): Promise<DossierSummaryWithInvoiceId | null> {
  try {
    const row = await api.getDossier(dossierId, { fresh: options?.fresh });
    return mapDossierDetailFromApi(row);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
