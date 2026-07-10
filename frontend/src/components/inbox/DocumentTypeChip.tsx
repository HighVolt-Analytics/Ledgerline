import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { documentTypeChipDisplayLabel } from "@/lib/documentTypeResolve";
import { documentTypeStatusChipClass } from "@/lib/documentTypeChipColors";
import { cn } from "@/lib/cn";

export function DocumentTypeChip({
  code,
  label,
  display,
  title,
  purchaseKind,
  documentTypes,
  className,
}: {
  code?: string | null;
  label?: string | null;
  /** Override visible chip text; otherwise uses compact document-type chip label */
  display?: string | null;
  title?: string;
  purchaseKind?: string | null;
  documentTypes?: DocumentTypeDefinition[] | null;
  className?: string;
}) {
  const token = (code ?? "").trim();
  const text =
    display?.trim() ||
    documentTypeChipDisplayLabel({ code, label, purchaseKind, documentTypes });
  const chipClass = documentTypeStatusChipClass({
    code,
    label,
    purchaseKind,
    documentTypes,
  });
  const tip = title ?? label?.trim() ?? (token ? text : "Document type not classified");

  return (
    <span className={cn(chipClass, className)} title={tip}>
      {text}
    </span>
  );
}