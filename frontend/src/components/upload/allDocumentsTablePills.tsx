import { AlertTriangle, Clock } from "lucide-react";
import type { ReactNode } from "react";
import type { MatrixRow } from "@/api/types";
import { cn } from "@/lib/cn";
import type { AllDocumentsNature, PipelineStatusLabel } from "@/lib/allDocumentsSummary";
import {
  documentTypeLabelForCode,
  storedDocumentTypeCode,
  visionDocumentTypeLabel,
} from "@/lib/documentTypeResolve";
import {
  approvalStatusChipClass,
  kpiStatusChipClass,
  warningStatusChipClass,
} from "@/lib/kpiModuleColors";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import type { MatrixPaymentStatus } from "@/lib/v4MatrixMockData";

export type TableStatusTone = "ok" | "approved" | "pending" | "fail" | "muted" | "hold" | "rose";

export function TableStatusTag({
  tone,
  children,
  title,
  className,
  testId,
  showDot = true,
}: {
  tone: TableStatusTone;
  children: ReactNode;
  title?: string;
  className?: string;
  testId?: string;
  showDot?: boolean;
}) {
  const withDot = showDot && tone !== "muted";
  return (
    <span
      className={cn("all-docs-status-tag", `all-docs-status-tag--${tone}`, className)}
      title={title}
      data-testid={testId}
    >
      {withDot ? <span className="all-docs-status-tag__dot" aria-hidden /> : null}
      <span className="all-docs-status-tag__label">{children}</span>
    </span>
  );
}

export function TypeBadge({
  inv,
}: {
  inv: MatrixRow["invoice"];
  documentTypes?: DocumentTypeDefinition[] | null;
}) {
  const vision = visionDocumentTypeLabel(inv);
  if (!vision) {
    return <span className="text-xs text-muted-foreground">—</span>;
  }
  return (
    <span className="text-xs truncate" title={vision}>
      {vision}
    </span>
  );
}

export function RouteText({
  inv,
  documentTypes,
}: {
  inv: MatrixRow["invoice"];
  documentTypes?: DocumentTypeDefinition[] | null;
}) {
  const code = storedDocumentTypeCode(inv);
  const typeLabel =
    (documentTypes?.length ? documentTypeLabelForCode(documentTypes, code) : null) || code;
  if (!code) {
    return <span className="text-xs text-muted-foreground">Not classified</span>;
  }
  return (
    <span className="text-xs truncate" title={typeLabel}>
      {typeLabel}
    </span>
  );
}

export function NatureBadge({ nature }: { nature: AllDocumentsNature }) {
  if (!nature) return <span className="text-muted-foreground text-xs">—</span>;
  return (
    <span className="text-xs truncate" title={nature}>
      {nature}
    </span>
  );
}

export function PipelineStatusBadge({ label }: { label: PipelineStatusLabel }) {
  if (label === "Done" || label === "Posted") {
    return (
      <TableStatusTag tone="ok" title={label}>
        {label}
      </TableStatusTag>
    );
  }
  if (label === "Failed") {
    return (
      <TableStatusTag tone="fail" title={label}>
        {label}
      </TableStatusTag>
    );
  }
  if (label === "Pending") {
    return (
      <TableStatusTag tone="pending" title={label}>
        {label}
      </TableStatusTag>
    );
  }
  if (label === "Not required" || label === "N/A") {
    return (
      <TableStatusTag tone="muted" title={label}>
        {label}
      </TableStatusTag>
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
    <TableStatusTag tone="rose" title={label} showDot={false}>
      {label}
    </TableStatusTag>
  );
}

export function PaymentStatusPill({ status }: { status: MatrixPaymentStatus }) {
  if (status === "Paid") {
    return (
      <TableStatusTag tone="ok" title={status}>
        {status}
      </TableStatusTag>
    );
  }
  if (status === "Payment Approved") {
    return (
      <TableStatusTag tone="approved" title={status}>
        {status}
      </TableStatusTag>
    );
  }
  if (status === "Awaiting Payment") {
    return (
      <TableStatusTag tone="pending" title={status}>
        {status}
      </TableStatusTag>
    );
  }
  if (status === "On Hold") {
    return (
      <TableStatusTag tone="hold" title={status}>
        {status}
      </TableStatusTag>
    );
  }
  if (status === "Failed") {
    return (
      <TableStatusTag tone="fail" title={status}>
        {status}
      </TableStatusTag>
    );
  }
  return <span className="text-muted-foreground text-xs font-normal">—</span>;
}

export function authSyncStatusTone(label: string): TableStatusTone {
  if (label === "Done" || label === "Synced") return "ok";
  if (label === "Failed") return "fail";
  if (label === "Pending") return "pending";
  return "muted";
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
