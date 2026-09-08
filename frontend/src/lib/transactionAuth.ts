/**
 * Transaction Auth — Privilege → Advance → Budget.
 * Click Pending in the table → card of pending steps → click a step → what to do.
 */
import type { Invoice, MatrixRow } from "@/api/types";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import {
  approvalStatusLabel,
  documentNature,
  type AllDocumentsNature,
} from "@/lib/allDocumentsSummary";
import type { MatrixCell, MatrixStage } from "@/lib/matrix";
import { normalizeAuthSyncLabel } from "@/lib/allDocumentsDetailed";

export type TransactionAuthKind = "privilege" | "advance" | "budget";
export type TransactionAuthStatus = "NA" | "Pending" | "Done" | "Failed";

export type TransactionAuthStep = {
  kind: TransactionAuthKind;
  label: string;
  detail: string;
  /** What the reviewer should do when this step is pending or failed. */
  actionNeeded: string;
  status: TransactionAuthStatus;
};

export type TransactionAuthView = {
  steps: TransactionAuthStep[];
  /** False when every step is NA — column shows NA, not clickable. */
  applicable: boolean;
  /** Steps that still need attention (Pending or Failed), in approval order. */
  actionableSteps: TransactionAuthStep[];
  /** First Pending in Privilege → Advance → Budget order. */
  primaryPending: TransactionAuthStep | null;
  displayStatus: TransactionAuthStatus;
};

const ORDER: TransactionAuthKind[] = ["privilege", "advance", "budget"];

const LABELS: Record<TransactionAuthKind, string> = {
  privilege: "Privilege Auth",
  advance: "Advance Auth",
  budget: "Budget Auth",
};

const DETAILS: Record<TransactionAuthKind, string> = {
  privilege: "Manager or policy approval before the document can continue",
  advance: "Advance / float control for team expense cash-out",
  budget: "Budget control and spend-limit checks",
};

const ACTIONS: Record<TransactionAuthKind, { pending: string; failed: string }> = {
  privilege: {
    pending:
      "Open Approvals (or the document drawer) and approve or reject this document. Privilege approval must clear before later auth steps can finish.",
    failed:
      "Privilege approval failed or was rejected. Re-open the document, fix the hold reason, then request approval again.",
  },
  advance: {
    pending:
      "Open Team Expenses for this claim. Confirm the advance / float requisition and complete advance authorization before posting.",
    failed:
      "Advance authorization failed. Review the advance amount and controls in Team Expenses, then reprocess or correct the claim.",
  },
  budget: {
    pending:
      "Open Team Expenses and resolve the budget check (VR-TE08). Confirm spend is within limit or obtain the required budget override.",
    failed:
      "Budget authorization failed (hard overrun or failed check). Adjust the claim amount or budget, then revalidate.",
  },
};

function toAuthStatus(raw: string | null | undefined): TransactionAuthStatus {
  const token = normalizeAuthSyncLabel(raw);
  if (token === "—" || token === "-" || !token) return "NA";
  if (token === "Pending") return "Pending";
  if (token === "Done" || token === "Synced") return "Done";
  if (token === "Failed") return "Failed";
  if (token === "Not required" || token === "N/A" || token === "NA") return "NA";
  return "NA";
}

function privilegeStatus(
  inv: Invoice,
  cells: Record<MatrixStage, MatrixCell>,
  documentTypes: DocumentTypeDefinition[] | null | undefined,
  nature: AllDocumentsNature
): TransactionAuthStatus {
  const label = approvalStatusLabel(inv, cells, documentTypes, nature);
  if (label === "Not required") return "NA";
  if (label === "Pending") return "Pending";
  if (label === "Done") return "Done";
  if (label === "Failed") return "Failed";
  return "NA";
}

function worstStatus(statuses: TransactionAuthStatus[]): TransactionAuthStatus {
  if (statuses.includes("Failed")) return "Failed";
  if (statuses.includes("Pending")) return "Pending";
  if (statuses.includes("Done")) return "Done";
  return "NA";
}

function actionFor(kind: TransactionAuthKind, status: TransactionAuthStatus): string {
  if (status === "Failed") return ACTIONS[kind].failed;
  if (status === "Pending") return ACTIONS[kind].pending;
  if (status === "Done") return "This authorization is complete — no further action needed.";
  return "This authorization does not apply to this document.";
}

export function buildTransactionAuthView(input: {
  inv: Invoice;
  matrixRow: MatrixRow;
  cells: Record<MatrixStage, MatrixCell>;
  documentTypes?: DocumentTypeDefinition[] | null;
  nature?: AllDocumentsNature;
}): TransactionAuthView {
  const nature = input.nature ?? documentNature(input.inv, input.documentTypes);
  const rawSteps: Omit<TransactionAuthStep, "actionNeeded">[] = [
    {
      kind: "privilege",
      label: LABELS.privilege,
      detail: DETAILS.privilege,
      status: privilegeStatus(input.inv, input.cells, input.documentTypes, nature),
    },
    {
      kind: "advance",
      label: LABELS.advance,
      detail: DETAILS.advance,
      status: toAuthStatus(input.matrixRow.advance_auth),
    },
    {
      kind: "budget",
      label: LABELS.budget,
      detail: DETAILS.budget,
      status: toAuthStatus(input.matrixRow.budget_auth),
    },
  ];

  const steps: TransactionAuthStep[] = rawSteps.map((step) => ({
    ...step,
    actionNeeded: actionFor(step.kind, step.status),
  }));

  const applicable = steps.some((s) => s.status !== "NA");
  const ordered = ORDER.map((kind) => steps.find((s) => s.kind === kind)!);
  const primaryPending = ordered.find((s) => s.status === "Pending") ?? null;
  const actionableSteps = ordered.filter(
    (s) => s.status === "Pending" || s.status === "Failed"
  );

  const displayStatus = applicable
    ? worstStatus(steps.map((s) => s.status))
    : "NA";

  return {
    steps,
    applicable,
    actionableSteps,
    primaryPending,
    displayStatus,
  };
}
