/**
 * Dossier approval chain — mirrors Ledgerline playbook gate, /approvals queue,
 * publish, and payment SoD. UI model until dossier API ships.
 */

import type { ApprovalMode } from "@/lib/documentPlaybookConfig";
import { approvalModeLabel } from "@/lib/documentPlaybookConfig";
import { paymentApproverCount } from "@/lib/v4MockData";

export type DossierApprovalStepState =
  | "done"
  | "pending"
  | "waived"
  | "blocked"
  | "skipped"
  | "not_required"
  | "fail";

export type DossierApprovalStepKind =
  | "po_buyer"
  | "document_gate"
  | "variance"
  | "exception_queue"
  | "publish"
  | "payment";

export type DossierApprovalStep = {
  id: string;
  kind: DossierApprovalStepKind;
  label: string;
  role: string;
  actor: string;
  state: DossierApprovalStepState;
  at: string | null;
  detail?: string;
  policyRef?: string;
  sodNote?: string;
};

export type DossierApprovalChain = {
  policyMode: ApprovalMode;
  policyLabel: string;
  steps: DossierApprovalStep[];
};

export function approvalStepStateLabel(state: DossierApprovalStepState): string {
  if (state === "done") return "Complete";
  if (state === "pending") return "Waiting";
  if (state === "waived") return "Not required";
  if (state === "not_required") return "N/A";
  if (state === "blocked") return "Blocked";
  if (state === "fail") return "Failed";
  if (state === "skipped") return "Skipped";
  return state;
}

const APPROVAL_DETAIL_HUMAN: Record<string, string> = {
  invoice_approved: "Approved in Approvals",
  "approval_required cleared": "Approval gate cleared",
  approval_required: "Waiting for approver",
  "Opens in /approvals when required": "Will appear in Approvals if needed",
};

export function approvalStepDetailHuman(detail?: string | null): string | undefined {
  if (!detail?.trim()) return undefined;
  const token = detail.trim();
  if (APPROVAL_DETAIL_HUMAN[token]) return APPROVAL_DETAIL_HUMAN[token];
  if (token.toLowerCase() === "invoice_approved") return APPROVAL_DETAIL_HUMAN.invoice_approved;
  if (token.toLowerCase().includes("approval_required") && token.toLowerCase().includes("cleared")) {
    return APPROVAL_DETAIL_HUMAN["approval_required cleared"];
  }
  return token;
}

export function approvalChainProgress(chain: DossierApprovalChain): {
  complete: number;
  total: number;
} {
  const total = chain.steps.length;
  const complete = chain.steps.filter(
    (step) =>
      step.state === "done" ||
      step.state === "waived" ||
      step.state === "not_required" ||
      step.state === "skipped"
  ).length;
  return { complete, total };
}

export function formatApprovalTimestamp(at: string | null): string | null {
  if (!at?.trim()) return null;
  // Backend dossier/pipeline timestamps are UTC wall-clock without a zone suffix.
  const token = at.trim().replace(" ", "T");
  const parsed = new Date(/[zZ]|[+-]\d{2}:?\d{2}$/.test(token) ? token : `${token}Z`);
  if (Number.isNaN(parsed.getTime())) return at;
  return parsed.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function paymentTierDetail(amount: number, currency: string): string {
  const count = paymentApproverCount(amount);
  const tier =
    amount < 1_000
      ? "< $1k"
      : amount < 10_000
        ? "$1k–$10k"
        : amount < 50_000
          ? "$10k–$50k"
          : "> $50k";
  return `${currency} ${amount.toLocaleString()} · ${tier} · ${count} approver${count === 1 ? "" : "s"}`;
}

function chain(policyMode: ApprovalMode, steps: DossierApprovalStep[]): DossierApprovalChain {
  return { policyMode, policyLabel: approvalModeLabel(policyMode), steps };
}

function step(
  partial: Omit<DossierApprovalStep, "id"> & { id?: string }
): DossierApprovalStep {
  return { id: partial.id ?? partial.kind, ...partial };
}

/** DT-01 clean 3-way match — PO approval satisfies DOA, touchless through post. */
export function poTouchlessApprovalChain(opts: {
  poBuyer?: string;
  exceptionActor?: string;
  exceptionAt?: string | null;
  published?: boolean;
  publishedAt?: string | null;
  paymentState?: DossierApprovalStepState;
  paymentAt?: string | null;
  paymentDetail?: string;
  total: number;
  currency: string;
}): DossierApprovalChain {
  const {
    poBuyer = "Buyer on PO",
    exceptionActor = "System",
    exceptionAt = null,
    published = true,
    publishedAt,
    paymentState = "done",
    paymentAt,
    paymentDetail,
    total,
    currency,
  } = opts;

  return chain("touchless_on_clean_match", [
    step({
      kind: "po_buyer",
      label: "PO buyer authorization",
      role: "Buyer",
      actor: poBuyer,
      state: "waived",
      at: null,
      detail: "PO approval on file satisfies DOA for this amount band",
      policyRef: "DOA-01",
    }),
    step({
      kind: "document_gate",
      label: "Document-type approval gate",
      role: "Approver",
      actor: "Policy engine",
      state: "waived",
      at: null,
      detail: "Clean 3-way match — touchless_on_clean_match",
      policyRef: "touchless_on_clean_match",
    }),
    step({
      kind: "exception_queue",
      label: "Exception queue approval",
      role: "Approver",
      actor: exceptionActor,
      state: exceptionAt ? "done" : "waived",
      at: exceptionAt,
      detail: exceptionAt ? "invoice_approved — pipeline continued" : "Not routed to /approvals",
      policyRef: "invoice_approved",
    }),
    step({
      kind: "publish",
      label: "Post to ledger",
      role: "Post",
      actor: published ? "System" : "—",
      state: published ? "done" : "pending",
      at: publishedAt ?? null,
      detail: published ? "Posted to general ledger" : "Awaiting post from Approvals / Ledger",
      policyRef: "Post",
    }),
    step({
      kind: "payment",
      label: "Payment disbursement",
      role: "Approver",
      actor: paymentState === "done" ? "Payments queue" : "—",
      state: paymentState,
      at: paymentAt ?? null,
      detail: paymentDetail ?? paymentTierDetail(total, currency),
      policyRef: "PAY-tier",
    }),
  ]);
}

/** DT-01 variance / match exception — buyer must approve before mapping. */
export function poVarianceApprovalChain(opts: {
  buyer: string;
  varianceDetail: string;
  total: number;
  currency: string;
}): DossierApprovalChain {
  return chain("variance_workflow", [
    step({
      kind: "po_buyer",
      label: "PO buyer authorization",
      role: "Buyer",
      actor: opts.buyer,
      state: "pending",
      at: null,
      detail: "Original PO approval does not cover price variance",
      policyRef: "DOA-01",
    }),
    step({
      kind: "variance",
      label: "Purchase variance approval",
      role: "Buyer",
      actor: opts.buyer,
      state: "pending",
      at: null,
      detail: opts.varianceDetail,
      policyRef: "variance_workflow",
    }),
    step({
      kind: "document_gate",
      label: "Document-type approval gate",
      role: "Approver",
      actor: "—",
      state: "blocked",
      at: null,
      detail: "approval_required — purchase_variance_pending",
      policyRef: "variance_workflow",
    }),
    step({
      kind: "exception_queue",
      label: "Exception queue approval",
      role: "Approver",
      actor: "—",
      state: "blocked",
      at: null,
      detail: "Opens in /approvals after variance cleared",
      policyRef: "invoice_approved",
    }),
    step({
      kind: "publish",
      label: "Post to ledger",
      role: "Post",
      actor: "—",
      state: "blocked",
      at: null,
      policyRef: "Post",
    }),
    step({
      kind: "payment",
      label: "Payment disbursement",
      role: "Approver",
      actor: "—",
      state: "blocked",
      at: null,
      detail: paymentTierDetail(opts.total, opts.currency),
      policyRef: "PAY-tier",
    }),
  ]);
}

/** Bundle / upstream fail — approval chain not reached. */
export function approvalChainBlocked(opts: {
  policyMode: ApprovalMode;
  blockedAfter: string;
  total: number;
  currency: string;
}): DossierApprovalChain {
  const reason = `Blocked — ${opts.blockedAfter} must pass first`;
  const blocked = (kind: DossierApprovalStepKind, label: string, role: string): DossierApprovalStep =>
    step({ kind, label, role, actor: "—", state: "blocked", at: null, detail: reason });

  return chain(opts.policyMode, [
    blocked("po_buyer", "PO buyer authorization", "Buyer"),
    blocked("document_gate", "Document-type approval gate", "Approver"),
    blocked("exception_queue", "Exception queue approval", "Approver"),
    blocked("publish", "Post to ledger", "Post"),
    blocked("payment", "Payment disbursement", "Approver"),
  ]);
}

/** DT-10 import — never touchless, multi-hat DOA. */
export function importDossierApprovalChain(opts: {
  importManager?: string;
  controller?: string;
}): DossierApprovalChain {
  return chain("never_touchless", [
    step({
      kind: "document_gate",
      label: "Import manager sign-off",
      role: "Import manager",
      actor: opts.importManager ?? "—",
      state: "pending",
      at: null,
      detail: "Bundle 3/6 — mandatory docs missing",
      policyRef: "never_touchless",
    }),
    step({
      kind: "document_gate",
      id: "controller_gate",
      label: "Controller approval",
      role: "Controller",
      actor: opts.controller ?? "—",
      state: "pending",
      at: null,
      detail: "Full DOA for landed-cost dossier",
      policyRef: "full_doa",
    }),
    step({
      kind: "exception_queue",
      label: "Exception queue approval",
      role: "Approver",
      actor: "—",
      state: "blocked",
      at: null,
      detail: "After import gates clear",
      policyRef: "invoice_approved",
    }),
    step({
      kind: "publish",
      label: "Post to ledger",
      role: "Post",
      actor: "—",
      state: "blocked",
      at: null,
      policyRef: "Post",
    }),
    step({
      kind: "payment",
      label: "Payment disbursement",
      role: "Approver",
      actor: "—",
      state: "blocked",
      at: null,
      detail: "After posting",
      policyRef: "PAY-tier",
    }),
  ]);
}

/** DT-02 non-PO — full DOA, no PO buyer step. */
export function nonPoDoaApprovalChain(opts: {
  approver: string;
  approverRole: string;
  gateState?: DossierApprovalStepState;
  gateDetail?: string;
  approvedAt?: string | null;
  published?: boolean;
  publishedAt?: string | null;
  paymentState?: DossierApprovalStepState;
  paymentAt?: string | null;
  total: number;
  currency: string;
  policyMode?: ApprovalMode;
}): DossierApprovalChain {
  const gateState = opts.gateState ?? (opts.approvedAt ? "done" : "pending");
  const queueDone = gateState === "done" || gateState === "waived";
  return chain(opts.policyMode ?? "full_doa", [
    step({
      kind: "document_gate",
      label: "DOA approval",
      role: opts.approverRole,
      actor: opts.approver,
      state: gateState,
      at: opts.approvedAt ?? null,
      detail:
        opts.gateDetail ??
        (gateState === "waived"
          ? "Below auto-approve threshold — manager gate waived"
          : gateState === "done"
            ? "approval_required cleared"
            : "Non-PO requires designated approver"),
      policyRef: "full_doa",
    }),
    step({
      kind: "exception_queue",
      label: "Exception queue approval",
      role: "Approver",
      actor: queueDone ? "System" : "—",
      state: queueDone ? "done" : "pending",
      at: opts.approvedAt ?? null,
      detail: "invoice_approved",
      policyRef: "invoice_approved",
    }),
    step({
      kind: "publish",
      label: "Post to ledger",
      role: "Post",
      actor: opts.published ? "System" : "—",
      state: opts.published ? "done" : "pending",
      at: opts.publishedAt ?? null,
      policyRef: "Post",
    }),
    step({
      kind: "payment",
      label: "Payment disbursement",
      role: "Approver",
      actor: opts.paymentState === "done" ? "Payments queue" : "—",
      state: opts.paymentState ?? "pending",
      at: opts.paymentAt ?? null,
      detail: paymentTierDetail(opts.total, opts.currency),
      policyRef: "PAY-tier",
    }),
  ]);
}

/** Touchless through approve; held on suspense GL — Finance Controller in queue. */
export function suspenseMappingApprovalChain(opts: {
  total: number;
  currency: string;
}): DossierApprovalChain {
  return chain("touchless_on_clean_match", [
    step({
      kind: "po_buyer",
      label: "PO buyer authorization",
      role: "Buyer",
      actor: "Policy engine",
      state: "waived",
      at: null,
      detail: "PO approval on file",
      policyRef: "DOA-01",
    }),
    step({
      kind: "document_gate",
      label: "Document-type approval gate",
      role: "Approver",
      actor: "Policy engine",
      state: "waived",
      at: null,
      policyRef: "touchless_on_clean_match",
    }),
    step({
      kind: "exception_queue",
      label: "Exception queue approval",
      role: "Finance Controller",
      actor: "—",
      state: "pending",
      at: null,
      detail: "mapping_review_required — suspense-routed invoice (ap3)",
      policyRef: "routing_review_required",
    }),
    step({
      kind: "publish",
      label: "Post to ledger",
      role: "Post",
      actor: "—",
      state: "blocked",
      at: null,
      detail: "After GL mapping resolved",
      policyRef: "Post",
    }),
    step({
      kind: "payment",
      label: "Payment disbursement",
      role: "Approver",
      actor: "—",
      state: "blocked",
      at: null,
      detail: paymentTierDetail(opts.total, opts.currency),
      policyRef: "PAY-tier",
    }),
  ]);
}

/** Posted but payment held — SoD on payment step. */
export function postedPaymentHoldChain(opts: {
  invoiceApprover: string;
  total: number;
  currency: string;
  paymentDetail: string;
}): DossierApprovalChain {
  return chain("touchless_on_clean_match", [
    step({
      kind: "po_buyer",
      label: "PO buyer authorization",
      role: "Buyer",
      actor: "Policy engine",
      state: "waived",
      at: null,
      detail: "Touchless — PO approval on file",
      policyRef: "DOA-01",
    }),
    step({
      kind: "document_gate",
      label: "Document-type approval gate",
      role: "Approver",
      actor: "Policy engine",
      state: "waived",
      at: null,
      policyRef: "touchless_on_clean_match",
    }),
    step({
      kind: "exception_queue",
      label: "Exception queue approval",
      role: "Approver",
      actor: opts.invoiceApprover,
      state: "done",
      at: "2026-02-03 09:40:42",
      detail: "invoice_approved",
      policyRef: "invoice_approved",
    }),
    step({
      kind: "publish",
      label: "Post to ledger",
      role: "Post",
      actor: "System",
      state: "done",
      at: "2026-02-03 09:40:50",
      policyRef: "Post",
    }),
    step({
      kind: "payment",
      label: "Payment disbursement",
      role: "Approver",
      actor: "—",
      state: "pending",
      at: null,
      detail: opts.paymentDetail,
      policyRef: "PAY-04",
      sodNote: `Segregation of duties: ${opts.invoiceApprover} approved this invoice — payment release needs another authorised approver.`,
    }),
  ]);
}

/** Stopped at duplicate — chain not applicable. */
export function duplicateSkippedApprovalChain(): DossierApprovalChain {
  return chain("touchless_on_clean_match", [
    step({
      kind: "document_gate",
      label: "Document-type approval gate",
      role: "Approver",
      actor: "—",
      state: "not_required",
      at: null,
      detail: "duplicate_skipped — pipeline halted before approval gate",
      policyRef: "ING-DUP",
    }),
  ]);
}
