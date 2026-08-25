import { useEffect, useState } from "react";
import { Building2, X } from "lucide-react";
import type { Customer } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

function slugify(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 100);
}

type CustomerFormDialogProps = {
  open: boolean;
  customer: Customer | null;
  onClose: () => void;
  onSave: (body: Omit<Customer, "id" | "created_at">) => Promise<void>;
};

export function CustomerFormDialog({
  open,
  customer,
  onClose,
  onSave,
}: CustomerFormDialogProps) {
  const [customerName, setCustomerName] = useState("");
  const [customerSlug, setCustomerSlug] = useState("");
  const [senderPattern, setSenderPattern] = useState("");
  const [abn, setAbn] = useState("");
  const [approved, setApproved] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !saving) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, saving]);

  useEffect(() => {
    if (!open) return;
    if (customer) {
      setCustomerName(customer.customer_name);
      setCustomerSlug(customer.customer_slug);
      setSenderPattern(customer.sender_pattern);
      setAbn(customer.abn ?? "");
      setApproved(customer.approved);
    } else {
      setCustomerName("");
      setCustomerSlug("");
      setSenderPattern("");
      setAbn("");
      setApproved(true);
    }
    setError(null);
  }, [open, customer]);

  if (!open) return null;

  async function submit() {
    setError(null);
    const name = customerName.trim();
    const slug = (customerSlug || slugify(name)).trim();
    const pattern = senderPattern.trim();
    if (!name || !slug || !pattern) {
      setError("Name, slug, and sender pattern are required.");
      return;
    }
    if (abn && !/^\d{11}$/.test(abn)) {
      setError("Business registration number must be 11 digits.");
      return;
    }
    setSaving(true);
    try {
      await onSave({
        customer_slug: slug,
        customer_name: name,
        sender_pattern: pattern,
        abn: abn || null,
        approved,
      });
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="app-modal-root" role="presentation">
      <button
        type="button"
        className="app-modal-backdrop"
        aria-label="Close dialog"
        onClick={onClose}
        disabled={saving}
      />
      <div
        role="dialog"
        aria-modal="true"
        className="app-modal-panel overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <div className="flex items-center gap-2 font-medium">
            <Building2 className="h-4 w-4 text-primary" />
            {customer ? "Edit customer" : "Add customer"}
          </div>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 space-y-3">
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <div>
            <label className="text-xs text-muted-foreground">Customer name</label>
            <Input
              value={customerName}
              onChange={(e) => {
                setCustomerName(e.target.value);
                if (!customer) setCustomerSlug(slugify(e.target.value));
              }}
              className="mt-0.5 h-9"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Slug</label>
            <Input
              value={customerSlug}
              onChange={(e) => setCustomerSlug(e.target.value)}
              className="mt-0.5 h-9 font-mono text-sm"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Sender pattern</label>
            <Input
              value={senderPattern}
              onChange={(e) => setSenderPattern(e.target.value)}
              placeholder="@customer.com"
              className="mt-0.5 h-9"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Business registration number (optional)</label>
            <Input
              value={abn}
              onChange={(e) => setAbn(e.target.value.replace(/\D/g, "").slice(0, 11))}
              className="mt-0.5 h-9 font-mono"
            />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={approved}
              onChange={(e) => setApproved(e.target.checked)}
            />
            Approved for auto-matching
          </label>
        </div>
        <div className="flex justify-end gap-2 px-4 py-3 border-t border-border">
          <Button variant="outline" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button size="sm" disabled={saving} onClick={() => void submit()}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}
