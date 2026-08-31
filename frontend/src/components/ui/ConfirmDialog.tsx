import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";

type ConfirmDialogProps = {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  "data-testid"?: string;
};

/** Accessible confirm modal — replaces window.confirm for destructive actions. */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  busy = false,
  onConfirm,
  onCancel,
  "data-testid": testId = "confirm-dialog",
}: ConfirmDialogProps) {
  const titleId = useId();
  const descId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    cancelRef.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onCancel();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, busy, onCancel]);

  if (!open) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center p-4"
      data-testid={testId}
      role="presentation"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/40"
        aria-label="Dismiss"
        disabled={busy}
        onClick={() => {
          if (!busy) onCancel();
        }}
      />
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        className={cn(
          "relative z-10 w-full max-w-md rounded-lg border border-border bg-popover p-4 shadow-lg"
        )}
      >
        <h2 id={titleId} className="text-sm font-semibold text-foreground">
          {title}
        </h2>
        {description ? (
          <p id={descId} className="mt-2 text-sm text-muted-foreground">
            {description}
          </p>
        ) : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button
            ref={cancelRef}
            type="button"
            size="sm"
            variant="outline"
            disabled={busy}
            onClick={onCancel}
            data-testid={`${testId}-cancel`}
          >
            {cancelLabel}
          </Button>
          <Button
            type="button"
            size="sm"
            variant={destructive ? "destructive" : "default"}
            disabled={busy}
            onClick={onConfirm}
            data-testid={`${testId}-confirm`}
          >
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
