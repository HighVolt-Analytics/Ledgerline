import { TableStatusTag, authSyncStatusTone } from "@/components/upload/allDocumentsTablePills";
import type { TransactionAuthView } from "@/lib/transactionAuth";
import { cn } from "@/lib/cn";

export function TransactionAuthCell({
  auth,
  onOpen,
  testId,
}: {
  auth: TransactionAuthView;
  onOpen: () => void;
  testId?: string;
}) {
  const label = !auth.applicable || auth.displayStatus === "NA" ? "NA" : auth.displayStatus;
  const tone =
    label === "NA" ? "muted" : authSyncStatusTone(auth.displayStatus);

  return (
    <button
      type="button"
      className={cn(
        "inline-flex max-w-full rounded-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        "hover:opacity-90 cursor-pointer"
      )}
      title="View Privilege, Advance, and Budget authorization"
      data-testid={testId}
      onClick={(e) => {
        e.stopPropagation();
        onOpen();
      }}
    >
      <TableStatusTag tone={tone} title={label} showDot={label !== "NA"}>
        {label}
      </TableStatusTag>
    </button>
  );
}
