import { useEffect, useState } from "react";
import { Building2, X } from "lucide-react";
import type { Vendor } from "@/api/types";
import { VendorPayoutMethodsPanel } from "@/components/vendors/VendorPayoutMethodsPanel";
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

type VendorFormDialogProps = {
  open: boolean;
  vendor: Vendor | null;
  onClose: () => void;
  onSave: (body: Omit<Vendor, "id" | "created_at">) => Promise<void>;
};

export function VendorFormDialog({
  open,
  vendor,
  onClose,
  onSave,
}: VendorFormDialogProps) {
  const [vendorName, setVendorName] = useState("");
  const [vendorSlug, setVendorSlug] = useState("");
  const [senderPattern, setSenderPattern] = useState("");
  const [abn, setAbn] = useState("");
  const [approved, setApproved] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    if (vendor) {
      setVendorName(vendor.vendor_name);
      setVendorSlug(vendor.vendor_slug);
      setSenderPattern(vendor.sender_pattern);
      setAbn(vendor.abn ?? "");
      setApproved(vendor.approved);
    } else {
      setVendorName("");
      setVendorSlug("");
      setSenderPattern("");
      setAbn("");
      setApproved(true);
    }
    setError(null);
  }, [open, vendor]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const isEdit = vendor != null;

  async function submit() {
    setError(null);
    const name = vendorName.trim();
    const slug = (vendorSlug || slugify(name)).trim();
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
        vendor_name: name,
        vendor_slug: slug,
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
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <button
        type="button"
        className="absolute inset-0 bg-black/80"
        aria-label="Close dialog"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        className="relative z-10 w-full max-w-md max-h-[90vh] overflow-y-auto rounded-lg border border-border bg-background p-6 shadow-lg"
      >
        <div className="flex items-center gap-2 mb-4">
          <Building2 className="h-5 w-5 text-primary" />
          <h4 className="text-sm font-semibold">{isEdit ? "Edit vendor" : "Add vendor"}</h4>
          <button type="button" onClick={onClose} className="ml-auto rounded-sm opacity-70 hover:opacity-100">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 text-sm">
          <div>
            <label className="text-xs text-muted-foreground">Vendor name</label>
            <Input
              value={vendorName}
              onChange={(e) => {
                setVendorName(e.target.value);
                if (!isEdit && !vendorSlug) setVendorSlug(slugify(e.target.value));
              }}
              className="mt-1 h-9"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Slug</label>
            <Input
              value={vendorSlug}
              onChange={(e) => setVendorSlug(e.target.value)}
              className="mt-1 h-9 tnum"
              disabled={isEdit}
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Sender pattern</label>
            <Input
              value={senderPattern}
              onChange={(e) => setSenderPattern(e.target.value)}
              placeholder="@vendor.com or billing@vendor.com"
              className="mt-1 h-9"
            />
          </div>
          <div>
            <label className="text-xs text-muted-foreground">Business registration number (optional)</label>
            <Input
              value={abn}
              onChange={(e) => setAbn(e.target.value.replace(/\D/g, "").slice(0, 11))}
              className="mt-1 h-9 tnum"
              placeholder="11 digits"
            />
          </div>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={approved}
              onChange={(e) => setApproved(e.target.checked)}
              className="rounded border-border"
            />
            Active (approved for processing)
          </label>
        </div>

        {error && <p className="mt-3 text-xs text-destructive">{error}</p>}

        {isEdit && vendor ? (
          <VendorPayoutMethodsPanel vendorId={vendor.id} />
        ) : (
          <p className="mt-5 border-t border-border pt-4 text-[11px] text-muted-foreground">
            Save the vendor before adding payout methods.
          </p>
        )}

        <div className="flex gap-2 mt-5">
          <Button variant="outline" className="flex-1" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button className="flex-1" onClick={() => void submit()} disabled={saving}>
            {saving ? "Saving…" : isEdit ? "Save changes" : "Add vendor"}
          </Button>
        </div>
      </div>
    </div>
  );
}
