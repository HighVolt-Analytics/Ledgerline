import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { FileDown, Landmark, Sparkles, X } from "lucide-react";
import { BankFileSettingsPanel } from "@/components/rule-book/BankFileSettingsPanel";
import { Button } from "@/components/ui/button";

const FORM_ID = "bank-file-settings-form";

export function BankFileSettingsDialog({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const [mounted, setMounted] = useState(false);
  const [dialogState, setDialogState] = useState<"open" | "closed">("closed");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      setDialogState("closed");
      const frame = requestAnimationFrame(() => {
        requestAnimationFrame(() => setDialogState("open"));
      });
      return () => cancelAnimationFrame(frame);
    }
    setDialogState("closed");
    const timer = window.setTimeout(() => setMounted(false), 220);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!mounted) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [mounted, onClose, saving]);

  if (!mounted) return null;

  return createPortal(
    <div
      className="app-modal-root app-modal-root--blur-strong"
      data-testid="bank-file-settings-dialog"
      data-state={dialogState}
      role="presentation"
    >
      <button
        type="button"
        className="app-modal-backdrop"
        aria-label="Dismiss"
        disabled={saving}
        onClick={() => {
          if (!saving) onClose();
        }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="bank-file-settings-title"
        className="app-modal-panel bank-file-settings-dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="bank-file-settings-dialog__header">
          <div className="relative flex items-start justify-between gap-4">
            <div className="flex items-start gap-3 min-w-0">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/10 text-primary shadow-sm">
                <Landmark className="h-5 w-5" />
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 id="bank-file-settings-title" className="text-base font-semibold tracking-tight">
                    Bank file settings
                  </h2>
                  <span className="inline-flex items-center gap-1 rounded-full border border-primary/20 bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary">
                    <Sparkles className="h-3 w-3" />
                    Batch export
                  </span>
                </div>
                <p className="mt-1 text-sm text-muted-foreground max-w-xl">
                  Set up your remitting account once, then bundle Scheduled payments into a bank-ready
                  file from this page.
                </p>
              </div>
            </div>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="relative h-8 w-8 shrink-0 p-0"
              aria-label="Close"
              disabled={saving}
              onClick={onClose}
              data-testid="bank-file-settings-dialog-close"
            >
              <X className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="bank-file-settings-dialog__body">
          <BankFileSettingsPanel
            embedded
            hideChrome
            formId={FORM_ID}
            onSaved={onClose}
            onSavingChange={setSaving}
          />
        </div>

        <div className="bank-file-settings-dialog__footer">
          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={saving}
            onClick={onClose}
          >
            Cancel
          </Button>
          <Button
            type="submit"
            size="sm"
            form={FORM_ID}
            disabled={saving}
            data-testid="bank-file-settings-save"
          >
            <FileDown className="h-3.5 w-3.5 mr-1.5" />
            {saving ? "Saving…" : "Save settings"}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
