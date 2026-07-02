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

export type DossierManualLinkInfoApi = {
  id: number;
  invoice_id: number;
  linked_dossier_id: string;
  document_ref?: string | null;
  label: string;
  document_type_code: string;
  has_file: boolean;
};

export type DossierLinkedDocumentApi = {
  id: string;
  document_type_code: string;
  label: string;
  document_ref?: string | null;
  invoice_no?: string | null;
  present: boolean;
  requirement: string;
  purchase_bundle_role?: string | null;
  sales_bundle_role?: string | null;
  source?: string | null;
  linked_dossier_id?: string | null;
  invoice_id?: number | null;
  is_anchor?: boolean;
  has_file?: boolean;
  linkage_detail?: string | null;
  link_kind?: string;
  manual_link_id?: number | null;
  manual_link?: DossierManualLinkInfoApi | null;
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
    currency: string;
    po_number?: string | null;
    po_qty?: number | null;
    po_unit_price?: number | null;
    po_value: number;
    po_date?: string | null;
    grn_present?: boolean;
    grn_qty?: number | null;
    grn_date?: string | null;
    grn_receiver?: string | null;
    grn_condition?: string | null;
    invoice_no?: string | null;
    invoice_qty?: number | null;
    invoice_unit_price?: number | null;
    invoice_value?: number;
    invoice_gst?: number;
    invoice_total: number;
    qty_variance_value?: number;
    price_variance_value?: number;
    total_deviation?: number;
    deviation: number;
  } | null;
  purchase_order_id?: number | null;
  sales_order_id?: number | null;
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
  counterparty_label?: string;
  route_target?: string | null;
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
  so_reference?: string | null;
  linkage_reference?: string | null;
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

function mapManualLinkInfo(info: DossierManualLinkInfoApi): import("@/lib/dossierLinkedDocuments").DossierManualLinkInfo {
  return {
    id: info.id,
    invoiceId: info.invoice_id,
    linkedDossierId: info.linked_dossier_id,
    documentRef: info.document_ref ?? null,
    label: info.label,
    documentTypeCode: info.document_type_code,
    hasFile: info.has_file,
  };
}

function mapLinkedDocument(doc: DossierLinkedDocumentApi): DossierLinkedDocument {
  return {
    id: doc.id,
    documentTypeCode: doc.document_type_code,
    label: doc.label,
    documentRef: doc.document_ref ?? null,
    invoiceNo: doc.invoice_no ?? null,
    present: doc.present,
    requirement: doc.requirement as DossierLinkedDocument["requirement"],
    purchaseBundleRole: (doc.purchase_bundle_role ?? undefined) as DossierLinkedDocument["purchaseBundleRole"],
    salesBundleRole: (doc.sales_bundle_role ?? undefined) as DossierLinkedDocument["salesBundleRole"],
    source: doc.source as DossierLinkedDocument["source"],
    linkedDossierId: doc.linked_dossier_id ?? null,
    invoiceId: doc.invoice_id ?? null,
    isAnchor: doc.is_anchor,
    hasFile: doc.has_file,
    linkageDetail: doc.linkage_detail ?? undefined,
    linkKind: (doc.link_kind === "manual"
      ? "manual"
      : doc.link_kind === "invoice_no"
        ? "invoice_no"
        : "system") as DossierLinkedDocument["linkKind"],
    manualLinkId: doc.manual_link_id ?? null,
    manualLink: doc.manual_link ? mapManualLinkInfo(doc.manual_link) : null,
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
          currency: linked.match_summary.currency,
          poNumber: linked.match_summary.po_number ?? null,
          poQty: linked.match_summary.po_qty ?? null,
          poUnitPrice: linked.match_summary.po_unit_price ?? null,
          poValue: linked.match_summary.po_value,
          poDate: linked.match_summary.po_date ?? null,
          grnPresent: linked.match_summary.grn_present ?? false,
          grnQty: linked.match_summary.grn_qty ?? null,
          grnDate: linked.match_summary.grn_date ?? null,
          grnReceiver: linked.match_summary.grn_receiver ?? null,
          grnCondition: linked.match_summary.grn_condition ?? null,
          invoiceNo: linked.match_summary.invoice_no ?? null,
          invoiceQty: linked.match_summary.invoice_qty ?? null,
          invoiceUnitPrice: linked.match_summary.invoice_unit_price ?? null,
          invoiceValue: linked.match_summary.invoice_value ?? 0,
          invoiceGst: linked.match_summary.invoice_gst ?? 0,
          invoiceTotal: linked.match_summary.invoice_total,
          qtyVarianceValue: linked.match_summary.qty_variance_value ?? 0,
          priceVarianceValue: linked.match_summary.price_variance_value ?? 0,
          totalDeviation:
            linked.match_summary.total_deviation ?? linked.match_summary.deviation ?? 0,
          deviation: linked.match_summary.deviation,
        }
      : undefined,
    purchaseOrderId: linked.purchase_order_id ?? null,
    salesOrderId: linked.sales_order_id ?? null,
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
  const routeTarget = row.route_target?.trim() || null;
  return {
    id: row.id,
    invoiceId: row.invoice_id,
    documentTypeCode: row.document_type_code,
    documentTypeTitle: row.document_type_title,
    vendor: row.vendor,
    counterpartyLabel: row.counterparty_label?.trim() || "Counterparty",
    routeTarget,
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
    soReference: row.so_reference ?? null,
    linkageReference: row.linkage_reference ?? null,
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

export function mapDossierListRowFromApi(row: DossierSummaryApi): DossierSummaryWithInvoiceId {
  return { ...mapDossierFromApi(row), invoiceId: row.invoice_id };
}

export function mapDossierDetailFromApi(row: DossierSummaryApi): DossierSummaryWithInvoiceId {
  return mapDossierListRowFromApi(row);
}

const DEFAULT_PAGE_SIZE = "12";

export async function fetchDossiersPage(params: {
  page: number;
  pageSize?: number;
  documentTypeCode?: string;
  q?: string;
  fresh?: boolean;
}): Promise<{
  rows: DossierSummaryWithInvoiceId[];
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
    rows: res.data.map(mapDossierListRowFromApi),
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

export async function addDossierManualLink(
  dossierId: string,
  body: { linkedInvoiceId: number; slotId?: string | null }
): Promise<DossierSummaryWithInvoiceId> {
  const row = await api.addDossierManualLink(dossierId, {
    linked_invoice_id: body.linkedInvoiceId,
    slot_id: body.slotId ?? null,
  });
  return mapDossierDetailFromApi(row);
}

export async function removeDossierManualLink(
  dossierId: string,
  linkId: number
): Promise<DossierSummaryWithInvoiceId> {
  const row = await api.removeDossierManualLink(dossierId, linkId);
  return mapDossierDetailFromApi(row);
}
