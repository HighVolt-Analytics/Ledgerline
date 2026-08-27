import { Check, Link2, Tags, X } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { Invoice } from "@/api/types";
import { ActionChip, type ActionChipTone } from "@/components/ActionChip";
import {
  documentRowActions,
  type DocumentRowAction,
  type DocumentRowActionKind,
  type DocumentRowDrawerTab,
} from "@/lib/documentRowActions";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { cn } from "@/lib/cn";

const KIND_META: Record<
  Exclude<DocumentRowActionKind, "none">,
  { icon: LucideIcon; tone: ActionChipTone }
> = {
  classify: { icon: Tags, tone: "review" },
  match: { icon: Link2, tone: "edit" },
  approve: { icon: Check, tone: "approve" },
  reject: { icon: X, tone: "reject" },
};

function runAction(
  action: DocumentRowAction,
  handlers: {
    onOpenDrawer: (tab?: DocumentRowDrawerTab) => void;
    onApprove: () => void;
    onReject: () => void;
  }
) {
  if (action.drawerTab) {
    handlers.onOpenDrawer(action.drawerTab);
    return;
  }
  if (action.kind === "approve") {
    handlers.onApprove();
    return;
  }
  if (action.kind === "reject") {
    handlers.onReject();
  }
}

export function UploadDocumentRowActions({
  inv,
  documentTypes,
  busy,
  pipelineActive,
  iconOnly = false,
  onOpenDrawer,
  onApprove,
  onReject,
}: {
  inv: Invoice;
  documentTypes?: DocumentTypeDefinition[] | null;
  busy: boolean;
  pipelineActive: boolean;
  iconOnly?: boolean;
  onOpenDrawer: (tab?: DocumentRowDrawerTab) => void;
  onApprove: () => void;
  onReject: () => void;
}) {
  const { primary, overflow } = documentRowActions(inv, documentTypes ?? undefined);
  if (primary.kind === "none") {
    return (
      <span className="text-muted-foreground text-xs" data-testid={`row-action-none-${inv.id}`}>
        —
      </span>
    );
  }

  const meta = KIND_META[primary.kind];
  const disabled = busy || pipelineActive;
  const handlers = { onOpenDrawer, onApprove, onReject };
  const rejectOverflow =
    !iconOnly
      ? overflow.find((item) => item.kind === "reject")
      : undefined;

  return (
    <span className={cn("inline-flex items-center gap-1 shrink-0", iconOnly && "justify-end")}>
      <ActionChip
        tone={meta.tone}
        icon={meta.icon}
        label={primary.label}
        iconOnly={iconOnly}
        busy={busy}
        disabled={disabled && !busy}
        onClick={() => runAction(primary, handlers)}
        testId={`row-action-${primary.kind}-${inv.id}`}
      />
      {rejectOverflow ? (
        <ActionChip
          tone="reject"
          icon={X}
          label={rejectOverflow.label}
          variant="outline"
          iconOnly
          busy={busy}
          disabled={disabled && !busy}
          onClick={() => runAction(rejectOverflow, handlers)}
          testId={`row-action-overflow-reject-${inv.id}`}
        />
      ) : null}
    </span>
  );
}
