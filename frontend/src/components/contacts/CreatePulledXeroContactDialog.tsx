import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type CreatePulledXeroContactDialogProps = {
  open: boolean;
  busy?: boolean;
  onClose: () => void;
  onSave: (name: string) => void;
};

export function CreatePulledXeroContactDialog({
  open,
  busy = false,
  onClose,
  onSave,
}: CreatePulledXeroContactDialogProps) {
  const titleId = useId();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setError(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, busy, onClose]);

  if (!open) return null;

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Enter a contact name.");
      return;
    }
    onSave(trimmed);
  };

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/40"
        aria-label="Close"
        disabled={busy}
        onClick={() => {
          if (!busy) onClose();
        }}
      />
      <form
        className="relative z-10 w-full max-w-md rounded-xl border border-border bg-background p-4 shadow-lg"
        onSubmit={handleSubmit}
        data-testid="create-pulled-contact-dialog"
        aria-labelledby={titleId}
      >
        <div className="mb-3 flex items-start justify-between gap-2">
          <h2 id={titleId} className="text-sm font-semibold">
            New Xero contact
          </h2>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={onClose}
            disabled={busy}
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        <label className="block text-sm">
          <span className="mb-1 block text-muted-foreground">Contact name</span>
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={busy}
            autoFocus
            data-testid="input-pulled-contact-name"
          />
        </label>
        {error ? <p className="mt-2 text-xs text-destructive">{error}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy} data-testid="button-save-pulled-contact">
            {busy ? "Saving…" : "Save"}
          </Button>
        </div>
      </form>
    </div>,
    document.body
  );
}
