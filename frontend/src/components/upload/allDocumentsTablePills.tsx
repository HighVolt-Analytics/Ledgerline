import { AlertTriangle, Clock } from "lucide-react";
import type { MatrixRow } from "@/api/types";
import { DocumentTypeChip } from "@/components/inbox/DocumentTypeChip";
import { StatusPill } from "@/components/StatusPill";
import { cn } from "@/lib/cn";
import type { AllDocumentsNature, PipelineStatusLabel } from "@/lib/allDocumentsSummary";
import { KLASS_TRANSACTIONAL } from "@/lib/documentTypeKlass";
import { storedDocumentTypeCode, visionDocumentTypeLabel } from "@/lib/documentTypeResolve";
import {
  approvalStatusChipClass,
  kpiStatusChipClass,
  warningStatusChipClass,
} from "@/lib/kpiModuleColors";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import type { MatrixPaymentStatus } from "@/lib/v4MatrixMockData";

/** Status / nature / payment tags — fully rounded pills. Type badges stay square with rounded corners. */
export const TABLE_PILL = "!rounded-full";

const PILL_SHELL = "font-normal border-border bg-muted/50";

export function TypeBadge({
  inv,
  documentTypes,
}: {
  inv: MatrixRow["invoice"];
  documentTypes?: DocumentTypeDefinition[] | null;
}) {
  const vision = visionDocumentTypeLabel(inv);
  if (!vision) {
    return <span className="text-xs text-muted-foreground" />;
  }
  return (
    <DocumentTypeChip
      code={storedDocumentTypeCode(inv) || undefined}
      label={vision}
      display={vision}
      title={vision}
      purchaseKind={inv.purchase_document_type}
      documentTypes={documentTypes}
      className="all-docs-type-badge max-w-full truncate font-normal !rounded-md"
    />
  );
}

export function NatureBadge({ nature }: { nature: AllDocumentsNature }) {
  if (!nature) return <span className="text-muted-foreground text-xs">—</span>;
  const transactional = nature === KLASS_TRANSACTIONAL;
  return (
    <span
      className={cn(
        transactional ? kpiStatusChipClass("blue") : approvalStatusChipClass("muted"),
        TABLE_PILL,
        "max-w-full truncate"
      )}
      title={nature}
    >
      {nature}
    </span>
  );
}

export function PipelineStatusBadge({ label }: { label: PipelineStatusLabel }) {
  if (label === "Done" || label === "Posted") {
    return (
      <StatusPill
        className={cn(PILL_SHELL, "all-docs-status-done max-w-full truncate")}
        style={{ color: "#16a34a" }}
        title={label}
      >
        {label}
      </StatusPill>
    );
  }
  if (label === "Failed") {
    return (
      <span className={cn(approvalStatusChipClass("reject"), TABLE_PILL, "max-w-full truncate")} title={label}>
        {label}
      </span>
    );
  }
  if (label === "Pending") {
    return (
      <StatusPill
        className={cn(PILL_SHELL, "all-docs-status-pending max-w-full truncate")}
        style={{ color: "#e6a800" }}
        title={label}
      >
        {label}
      </StatusPill>
    );
  }
  if (label === "Not required" || label === "N/A") {
    return (
      <span className={cn(approvalStatusChipClass("muted"), TABLE_PILL, "max-w-full truncate")} title={label}>
        {label}
      </span>
    );
  }
  return (
    <span className="text-muted-foreground text-xs font-normal all-docs-clip" title={label}>
      {label}
    </span>
  );
}

export function DuplicatePossibleBadge({ label }: { label: string }) {
  return (
    <span className={cn(kpiStatusChipClass("rose"), TABLE_PILL, "max-w-full truncate")} title={label}>
      {label}
    </span>
  );
}

export function PaymentStatusPill({ status }: { status: MatrixPaymentStatus }) {
  if (status === "Paid" || status === "Payment Approved") {
    return (
      <StatusPill
        className={cn(PILL_SHELL, "all-docs-status-done max-w-full truncate")}
        style={{ color: "#16a34a" }}
        title={status}
      >
        {status}
      </StatusPill>
    );
  }
  if (status === "Awaiting Payment") {
    return (
      <StatusPill
        className={cn(PILL_SHELL, "all-docs-status-pending max-w-full truncate")}
        style={{ color: "#e6a800" }}
        title={status}
      >
        {status}
      </StatusPill>
    );
  }
  if (status === "On Hold") {
    return (
      <span className={cn(approvalStatusChipClass("muted"), TABLE_PILL, "max-w-full truncate")} title={status}>
        {status}
      </span>
    );
  }
  if (status === "Failed") {
    return (
      <span className={cn(approvalStatusChipClass("reject"), TABLE_PILL, "max-w-full truncate")} title={status}>
        {status}
      </span>
    );
  }
  return <span className="text-muted-foreground text-xs font-normal">—</span>;
}

const ACTION_TAG =
  "all-docs-type-badge max-w-full truncate font-normal !rounded-md inline-flex items-center gap-1";

function actionTagChipClass(label: string): string {
  switch (label) {
    case "Duplicate Suspected":
      return kpiStatusChipClass("rose");
    case "Type missing":
      return kpiStatusChipClass("violet");
    case "Nature unknown":
      return kpiStatusChipClass("sage");
    case "Counterparty missing":
      return kpiStatusChipClass("teal");
    case "Doc date missing":
      return kpiStatusChipClass("cyan");
    case "Ledger missing":
      return kpiStatusChipClass("blue");
    case "Ledger in suspense":
      return kpiStatusChipClass("rust");
    case "Anomaly Detected":
    case "Quarantined":
    case "Approval failed":
    case "Posting failed":
    case "Payment failed":
      return approvalStatusChipClass("reject");
    case "Awaiting approval":
    case "Approval pending":
      return approvalStatusChipClass("pending");
    case "Awaiting linkage":
      return approvalStatusChipClass("edit");
    case "Payment on hold":
      return approvalStatusChipClass("muted");
    default:
      return warningStatusChipClass();
  }
}

export function ActionCell({
  primary,
  all,
  testId,
}: {
  primary: { label: string; detail?: string } | null;
  all: { label: string; detail?: string }[];
  testId?: string;
}) {
  if (!primary) {
    return (
      <span className="text-muted-foreground text-xs font-normal" data-testid={testId}>
        —
      </span>
    );
  }
  const title = all
    .map((issue) => (issue.detail ? `${issue.label}: ${issue.detail}` : issue.label))
    .join("\n");
  const anomaly = primary.label === "Anomaly Detected";
  const awaitingApproval =
    primary.label === "Awaiting approval" || primary.label === "Approval pending";
  return (
    <span title={title} data-testid={testId} className="inline-flex max-w-full">
      <span className={cn(actionTagChipClass(primary.label), ACTION_TAG)}>
        {anomaly ? (
          <AlertTriangle className="h-3 w-3 shrink-0" aria-hidden />
        ) : null}
        {awaitingApproval ? <Clock className="h-3 w-3 shrink-0" aria-hidden /> : null}
        <span className="truncate">{primary.label}</span>
      </span>
    </span>
  );
}
