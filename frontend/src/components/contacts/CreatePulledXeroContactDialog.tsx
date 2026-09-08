import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";

export type PulledContactDraft = {
  legal_name: string;
  entity_type: "vendor" | "customer";
  company_name?: string;
  given_name?: string;
  family_name?: string;
  email?: string;
  phone?: string;
  tax_identifier?: string;
};

type CreatePulledXeroContactDialogProps = {
  open: boolean;
  busy?: boolean;
  provider?: "xero" | "quickbooks";
  onClose: () => void;
  onSave: (draft: PulledContactDraft) => void;
};

function optional(value: string): string | undefined {
  const trimmed = value.trim();
  return trimmed || undefined;
}

export function CreatePulledXeroContactDialog({
  open,
  busy = false,
  provider = "xero",
  onClose,
  onSave,
}: CreatePulledXeroContactDialogProps) {
  const titleId = useId();
  const isQbo = provider === "quickbooks";
  const [name, setName] = useState("");
  const [entityType, setEntityType] = useState<"vendor" | "customer">("vendor");
  const [companyName, setCompanyName] = useState("");
  const [givenName, setGivenName] = useState("");
  const [familyName, setFamilyName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [taxIdentifier, setTaxIdentifier] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setName("");
    setEntityType("vendor");
    setCompanyName("");
    setGivenName("");
    setFamilyName("");
    setEmail("");
    setPhone("");
    setTaxIdentifier("");
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
    if (isQbo && !entityType) {
      setError("Choose Vendor or Customer.");
      return;
    }
    onSave({
      legal_name: trimmed,
      entity_type: isQbo ? entityType : "vendor",
      company_name: optional(companyName),
      given_name: optional(givenName),
      family_name: optional(familyName),
      email: optional(email),
      phone: optional(phone),
      tax_identifier: optional(taxIdentifier),
    });
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
            {isQbo ? "New QuickBooks contact" : "New Xero contact"}
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
        {isQbo ? (
          <label className="mb-3 block text-sm">
            <span className="mb-1 block text-muted-foreground">Type</span>
            <Select
              value={entityType}
              onValueChange={(value) => setEntityType(value === "customer" ? "customer" : "vendor")}
              options={[
                { value: "vendor", label: "Vendor" },
                { value: "customer", label: "Customer" },
              ]}
              disabled={busy}
            />
          </label>
        ) : null}
        <label className="block text-sm">
          <span className="mb-1 block text-muted-foreground">
            {isQbo ? "Display name" : "Contact name"}
          </span>
          <Input
            value={name}
            onChange={(event) => setName(event.target.value)}
            disabled={busy}
            autoFocus
            data-testid="input-pulled-contact-name"
          />
        </label>
        {isQbo ? (
          <div className="mt-3 space-y-3">
            <p className="text-[11px] text-muted-foreground">
              QuickBooks only requires display name and type. The rest is optional.
            </p>
            <label className="block text-sm">
              <span className="mb-1 block text-muted-foreground">Company name</span>
              <Input value={companyName} onChange={(event) => setCompanyName(event.target.value)} disabled={busy} />
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-sm">
                <span className="mb-1 block text-muted-foreground">First name</span>
                <Input value={givenName} onChange={(event) => setGivenName(event.target.value)} disabled={busy} />
              </label>
              <label className="block text-sm">
                <span className="mb-1 block text-muted-foreground">Last name</span>
                <Input value={familyName} onChange={(event) => setFamilyName(event.target.value)} disabled={busy} />
              </label>
            </div>
            <label className="block text-sm">
              <span className="mb-1 block text-muted-foreground">Email</span>
              <Input value={email} onChange={(event) => setEmail(event.target.value)} disabled={busy} />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-muted-foreground">Phone</span>
              <Input value={phone} onChange={(event) => setPhone(event.target.value)} disabled={busy} />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block text-muted-foreground">Tax ID / ABN</span>
              <Input
                value={taxIdentifier}
                onChange={(event) => setTaxIdentifier(event.target.value)}
                disabled={busy}
              />
            </label>
          </div>
        ) : null}
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
