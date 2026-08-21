/**
 * All Documents summary column helpers — nature, approval, posting, action, vault.
 */
import type { Invoice, MatrixRow } from "@/api/types";
import {
  normalizeDocumentTypeKlass,
  type DocumentTypeClass,
} from "@/lib/documentTypeKlass";
import { storedDocumentTypeCode, visionDocumentTypeLabel } from "@/lib/documentTypeResolve";
import {
  counterpartyName,
  glPostingApplicable,
  type ValidationPassDocumentType,
} from "@/lib/invoice";
import { invoiceRoutedToSuspense, matrixStageSettled, type MatrixCell, type MatrixStage } from "@/lib/matrix";
import { stagesToCells } from "@/lib/matrixApi";
import type { MatrixFlagType, MatrixPaymentStatus } from "@/lib/v4MatrixMockData";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

export type AllDocumentsChannelTab = "all" | "upload" | "email" | "whatsapp" | "viber";

export type PipelineStatusLabel = "Done" | "Pending" | "Failed" | "Not required" | "Posted" | "N/A";

export type AllDocumentsNature = DocumentTypeClass | null;

export type VaultCellValue =
  | { kind: "vaulted"; label: "Vaulted" }
  | { kind: "po"; label: string }
  | { kind: "so"; label: string }
  | { kind: "empty"; label: "—" };

export function parseUploadChannelTab(value: string | null): AllDocumentsChannelTab {
  if (
    value === "all" ||
    value === "upload" ||
    value === "email" ||
    value === "whatsapp" ||
    value === "viber"
  ) {
    return value;
  }
  return "all";
}

export function documentNature(
  inv: Pick<Invoice, "document_type_code">,
  documentTypes?: DocumentTypeDefinition[] | null
): AllDocumentsNature {
  const code = storedDocumentTypeCode(inv);
  if (!code || !documentTypes?.length) return null;
  const defn = documentTypes.find((dt) => dt.code.toUpperCase() === code);
  if (!defn) return null;
  return normalizeDocumentTypeKlass(defn.klass);
}

export function formatDocDate(invoiceDate: string | null | undefined): string {
  const raw = (invoiceDate ?? "").trim();
  if (!raw) return "—";
  const day = raw.slice(0, 10);
  if (/^\d{4}-\d{2}-\d{2}$/.test(day)) return day;
  const parsed = Date.parse(raw);
  if (Number.isNaN(parsed)) return raw;
  return new Date(parsed).toISOString().slice(0, 10);
}

function stageCell(
  cells: Record<MatrixStage, MatrixCell>,
  stage: MatrixStage
): MatrixCell {
  return cells[stage] ?? { state: "pending", ts: "—", detail: "—" };
}

export function approvalStatusLabel(
  inv: Pick<Invoice, "evaluation_status" | "published_to_ledger" | "gl_posting_applicable" | "route_target" | "purchase_document_type" | "sales_document_type" | "document_type_code">,
  cells: Record<MatrixStage, MatrixCell>,
  documentTypes?: ValidationPassDocumentType[] | null,
  nature?: AllDocumentsNature
): PipelineStatusLabel {
  if (nature === "Non-transactional" || !glPostingApplicable(inv, documentTypes)) {
    return "Not required";
  }
  const evalStatus = (inv.evaluation_status ?? "").trim().toLowerCase();
  if (evalStatus === "pending_approval") return "Pending";
  const cell = stageCell(cells, "Approved");
  if (cell.state === "fail") return "Failed";
  if (cell.state === "skipped") return "Not required";
  if (matrixStageSettled(cell.state)) return "Done";
  return "Pending";
}

export function postingStatusLabel(
  inv: Pick<Invoice, "published_to_ledger" | "gl_posting_applicable" | "route_target" | "purchase_document_type" | "sales_document_type" | "document_type_code">,
  cells: Record<MatrixStage, MatrixCell>,
  documentTypes?: ValidationPassDocumentType[] | null,
  nature?: AllDocumentsNature
): PipelineStatusLabel {
  if (nature === "Non-transactional" || !glPostingApplicable(inv, documentTypes)) {
    return "N/A";
  }
  if (inv.published_to_ledger) return "Posted";
  const cell = stageCell(cells, "Posted");
  if (cell.state === "fail") return "Failed";
  if (cell.state === "skipped") return "N/A";
  if (matrixStageSettled(cell.state)) return "Posted";
  return "Pending";
}

export function paymentStatusForNature(
  payment: MatrixPaymentStatus,
  nature: AllDocumentsNature
): MatrixPaymentStatus {
  if (nature === "Non-transactional") return "—";
  return payment;
}

export function vaultCellValue(
  inv: Pick<Invoice, "evaluation_status" | "route_target" | "po_reference" | "so_reference">
): VaultCellValue {
  const evalStatus = (inv.evaluation_status ?? "").trim().toLowerCase();
  const route = (inv.route_target ?? "").trim();
  if (evalStatus === "vision_vaulted" || route === "Vault") {
    return { kind: "vaulted", label: "Vaulted" };
  }
  const po = (inv.po_reference ?? "").trim();
  if (po) return { kind: "po", label: po };
  const so = (inv.so_reference ?? "").trim();
  if (so) return { kind: "so", label: so };
  return { kind: "empty", label: "—" };
}

export function toMatrixFlagType(value: string): MatrixFlagType {
  if (value === "Anomaly Detected") return "Anomaly Detected";
  if (value === "Duplicate Suspected") return "Duplicate Suspected";
  if (value === "Quarantined") return "Quarantined";
  if (value === "Awaiting approval") return "Awaiting approval";
  if (value === "Awaiting linkage") return "Awaiting linkage";
  return "Clean";
}

export function toMatrixPaymentStatus(value: string): MatrixPaymentStatus {
  const allowed: MatrixPaymentStatus[] = [
    "Paid",
    "Awaiting Payment",
    "Payment Approved",
    "On Hold",
    "Failed",
    "—",
  ];
  return allowed.includes(value as MatrixPaymentStatus)
    ? (value as MatrixPaymentStatus)
    : "—";
}

export type AllDocumentsActionIssue = {
  label: string;
  detail?: string;
};

/**
 * Primary Action issue for the All Documents summary row.
 * First match wins; callers may show `all` in a tooltip.
 */
export function allDocumentsActionIssues(input: {
  inv: Invoice;
  flag: MatrixFlagType;
  flagReason?: string | null;
  cells: Record<MatrixStage, MatrixCell>;
  payment: MatrixPaymentStatus;
  nature: AllDocumentsNature;
  documentTypes?: DocumentTypeDefinition[] | null;
}): { primary: AllDocumentsActionIssue | null; all: AllDocumentsActionIssue[] } {
  const { inv, flag, flagReason, cells, payment, nature, documentTypes } = input;
  const issues: AllDocumentsActionIssue[] = [];
  const postingApplies = glPostingApplicable(inv, documentTypes);
  const transactional = nature === "Transactional";
  const parseSettled = matrixStageSettled(stageCell(cells, "Parsed").state);

  if (flag !== "Clean") {
    issues.push({
      label: flag,
      detail: (flagReason ?? "").trim() || undefined,
    });
  }

  if (parseSettled && !visionDocumentTypeLabel(inv)) {
    issues.push({ label: "Type missing" });
  }

  if (transactional) {
    const name = counterpartyName(inv);
    if (!name || name === "—") {
      issues.push({ label: "Counterparty missing" });
    }
  }

  if (parseSettled && nature == null && !storedDocumentTypeCode(inv)) {
    issues.push({ label: "Nature unknown" });
  }

  if (transactional && !(inv.invoice_date ?? "").trim()) {
    issues.push({ label: "Doc date missing" });
  }

  if (postingApplies) {
    if (invoiceRoutedToSuspense(inv)) {
      issues.push({ label: "Ledger in suspense" });
    } else if (!(inv.account_name ?? "").trim()) {
      const mapped = matrixStageSettled(stageCell(cells, "Mapped").state);
      if (mapped) issues.push({ label: "Ledger missing" });
    }
  }

  const approval = approvalStatusLabel(inv, cells, documentTypes, nature);
  if (approval === "Failed") issues.push({ label: "Approval failed" });
  else if (approval === "Pending" && (inv.evaluation_status ?? "").trim().toLowerCase() === "pending_approval") {
    issues.push({ label: "Approval pending" });
  }

  const posting = postingStatusLabel(inv, cells, documentTypes, nature);
  if (posting === "Failed") issues.push({ label: "Posting failed" });

  const pay = paymentStatusForNature(payment, nature);
  if (pay === "Failed") issues.push({ label: "Payment failed" });
  else if (pay === "On Hold") issues.push({ label: "Payment on hold" });

  const deduped: AllDocumentsActionIssue[] = [];
  const seen = new Set<string>();
  for (const issue of issues) {
    const key = `${issue.label}|${issue.detail ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(issue);
  }

  return { primary: deduped[0] ?? null, all: deduped };
}

export function matrixRowCells(row: MatrixRow): Record<MatrixStage, MatrixCell> {
  return stagesToCells(row.stages);
}
