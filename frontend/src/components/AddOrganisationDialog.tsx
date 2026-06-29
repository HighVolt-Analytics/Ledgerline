import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { api } from "@/api/client";
import { useAuth } from "@/context/AuthContext";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type AddOrganisationDialogProps = {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
};

function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 100);
}

export function AddOrganisationDialog({
  open,
  onClose,
  onCreated,
}: AddOrganisationDialogProps) {
  const { switchOrganisation } = useAuth();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugTouched, setSlugTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setSlug("");
    setSlugTouched(false);
    setError(null);
  }, [open]);

  useEffect(() => {
    if (!slugTouched) {
      setSlug(slugify(name));
    }
  }, [name, slugTouched]);

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
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, busy]);

  if (!open) return null;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim() || !slug.trim()) {
      setError("Name and slug are required.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const org = await api.createOrganisation({
        name: name.trim(),
        slug: slug.trim().toLowerCase(),
      });
      await switchOrganisation(org.id);
      onCreated();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create organisation");
    } finally {
      setBusy(false);
    }
  }

  return createPortal(
    <div className="app-modal-root" role="presentation">
      <button
        type="button"
        className="app-modal-backdrop"
        aria-label="Close dialog"
        onClick={onClose}
        disabled={busy}
      />
      <form
        onSubmit={handleSubmit}
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-org-title"
        className="app-modal-panel p-6 space-y-4"
        data-testid="dialog-add-organisation"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 id="add-org-title" className="text-lg font-semibold leading-none">
              Add organisation
            </h2>
            <p className="text-sm text-muted-foreground mt-2">
              Create a demo tenant. You will be switched to it immediately — data is isolated
              per organisation.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-sm p-1 opacity-70 hover:opacity-100 transition-opacity shrink-0"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="org-name">
            Organisation name
          </label>
          <Input
            id="org-name"
            data-testid="input-org-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Acme Hospitality Pty Ltd"
            required
            autoFocus
          />
        </div>
        <div className="space-y-2">
          <label className="text-sm font-medium" htmlFor="org-slug">
            Slug
          </label>
          <Input
            id="org-slug"
            data-testid="input-org-slug"
            value={slug}
            onChange={(e) => {
              setSlugTouched(true);
              setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""));
            }}
            placeholder="acme-hospitality"
            pattern="[-a-z0-9]+"
            required
          />
        </div>
        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" data-testid="button-submit-org" disabled={busy}>
            {busy ? "Creating…" : "Create & switch"}
          </Button>
        </div>
      </form>
    </div>,
    document.body
  );
}
