import type { Invoice } from "@/api/types";
import { DocumentTypeChip } from "@/components/inbox/DocumentTypeChip";
import { RouteTargetBadge } from "@/components/inbox/EvaluationStatusBadge";
import {
  documentTypeLabelForCode,
  storedDocumentTypeCode,
  visionDocumentTypeLabel,
} from "@/lib/documentTypeResolve";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { cn } from "@/lib/cn";

/** Type column: printed / AI vision heading only — never catalogue DT title. */
export function VisionHeadingBadge({
  inv,
  className,
  empty = "—",
}: {
  inv: Pick<Invoice, "document_heading" | "extracted_fields">;
  className?: string;
  empty?: string;
}) {
  const vision = visionDocumentTypeLabel(inv);
  if (!vision) {
    return <span className={cn("text-xs text-muted-foreground", className)}>{empty}</span>;
  }
  return (
    <span className={cn("inline-flex max-w-full", className)}>
      <RouteTargetBadge route={vision} />
    </span>
  );
}

/** Route column: mapped Rule Book DT, or a "Not classified" signal. */
export function MappedDocumentTypeBadge({
  inv,
  documentTypes,
  onOpenClassification,
  className,
  testId,
}: {
  inv: Pick<Invoice, "document_type_code" | "purchase_document_type">;
  documentTypes?: DocumentTypeDefinition[] | null;
  onOpenClassification?: () => void;
  className?: string;
  testId?: string;
}) {
  const code = storedDocumentTypeCode(inv);
  const typeLabel =
    (documentTypes?.length ? documentTypeLabelForCode(documentTypes, code) : null) || code;

  if (code) {
    return (
      <span className={cn("inline-flex max-w-full", className)} data-testid={testId}>
        <DocumentTypeChip
          code={code}
          label={typeLabel}
          display={typeLabel}
          title={typeLabel}
          purchaseKind={inv.purchase_document_type}
          documentTypes={documentTypes}
        />
      </span>
    );
  }

  return (
    <span
      role={onOpenClassification ? "button" : undefined}
      tabIndex={onOpenClassification ? 0 : undefined}
      data-testid={testId ?? "route-not-classified"}
      className={cn(
        "inline-flex",
        onOpenClassification ? "cursor-pointer" : undefined,
        className
      )}
      title="Document type not classified — open to classify"
      onClick={
        onOpenClassification
          ? (e) => {
              e.stopPropagation();
              onOpenClassification();
            }
          : undefined
      }
      onKeyDown={
        onOpenClassification
          ? (e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                e.stopPropagation();
                onOpenClassification();
              }
            }
          : undefined
      }
    >
      <DocumentTypeChip
        display="Not classified"
        title="Document type not classified — open to classify"
      />
    </span>
  );
}
