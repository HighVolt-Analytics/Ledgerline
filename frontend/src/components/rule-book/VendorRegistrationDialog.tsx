import { useEffect, useState } from "react";
import { ClipboardCheck, X } from "lucide-react";
import { api } from "@/api/client";
import type { Invoice } from "@/api/types";
import { Button } from "@/components/ui/button";
import type { PendingVendorRecord } from "@/lib/masterDataApi";
import type { VendorMaster } from "@/lib/v4RuleBookTypes";
import { VendorDetailPanel } from "./VendorDetailPanel";

function fillIfEmpty(current: string, next?: string | null): string {
  if (current.trim()) return current;
  return (next ?? "").trim();
}

function applyInvoiceToVendorDraft(draft: VendorMaster, invoice: Invoice): VendorMaster {
  const extracted = invoice.extracted_fields ?? {};
  return {
    ...draft,
    name: fillIfEmpty(draft.name, invoice.vendor),
    abn: fillIfEmpty(draft.abn, invoice.abn),
    billingAddress: {
      street: fillIfEmpty(draft.billingAddress.street, invoice.billing_address),
      suburb: draft.billingAddress.suburb,
      postcode: draft.billingAddress.postcode,
      country: draft.billingAddress.country,
    },
    bank: {
      ...draft.bank,
      bsb: fillIfEmpty(draft.bank.bsb ?? "", invoice.bank_bsb) || draft.bank.bsb,
      accountNumber: fillIfEmpty(draft.bank.accountNumber, invoice.bank_account),
      bankName: fillIfEmpty(
        draft.bank.bankName,
        typeof extracted.bank_name === "string" ? extracted.bank_name : undefined,
      ),
    },
    defaultLedger: fillIfEmpty(draft.defaultLedger, invoice.account_name),
  };
}

export function vendorDraftFromPending(
  item: Pick<
    PendingVendorRecord,
    "id" | "detectedName" | "detectedAbn" | "detectedAddress" | "confidence"
  >,
): VendorMaster {
  return {
    id: `pending-${item.id}`,
    name: item.detectedName,
    aliases: [],
    abn: item.detectedAbn ?? "",
    billingAddress: {
      street: item.detectedAddress ?? "",
      suburb: "",
      postcode: "",
      country: "",
    },
    bank: { accountNumber: "", accountName: "", bankName: "" },
    defaultLedger: "",
    defaultSubLedger: "",
    paymentTerms: "",
    status: "Active",
    registeredOn: "",
    totalSpendYTD: 0,
    invoiceCount: 0,
    matchConfidence: item.confidence,
    contactEmail: "",
    contactPhone: "",
  };
}

export function VendorRegistrationDialog({
  open,
  initialVendor,
  sourceInvoiceId,
  onClose,
  onSave,
  saving,
}: {
  open: boolean;
  initialVendor: VendorMaster | null;
  sourceInvoiceId?: number;
  onClose: () => void;
  onSave: (vendor: VendorMaster) => void;
  saving: boolean;
}) {
  const [draft, setDraft] = useState<VendorMaster | null>(null);
  const [bankMasked, setBankMasked] = useState(false);

  useEffect(() => {
    if (!open || !initialVendor) {
      setDraft(null);
      return;
    }
    setDraft(initialVendor);
    setBankMasked(false);
  }, [open, initialVendor]);

  useEffect(() => {
    if (!open || !sourceInvoiceId) return;
    let cancelled = false;
    void api
      .getInvoice(sourceInvoiceId)
      .then((invoice) => {
        if (cancelled) return;
        setDraft((prev) => (prev ? applyInvoiceToVendorDraft(prev, invoice) : prev));
      })
      .catch(() => {
        /* Keep the pending-queue draft if the source invoice cannot be loaded. */
      });
    return () => {
      cancelled = true;
    };
  }, [open, sourceInvoiceId]);

  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !saving) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [open, onClose, saving]);

  if (!open || !draft) return null;

  return (
    <div className="vendor-registration-dialog-root">
      <button
        type="button"
        className="absolute inset-0 bg-black/80"
        aria-label="Close dialog"
        onClick={() => {
          if (!saving) onClose();
        }}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="vendor-registration-title"
        className="vendor-registration-dialog"
        data-testid="dialog-complete-vendor-registration"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-center justify-between gap-4 px-5 pt-5 pb-3">
          <div className="min-w-0">
            <h2 id="vendor-registration-title" className="text-lg font-semibold leading-none">
              Complete registration
            </h2>
            <p className="mt-1 truncate text-xs text-muted-foreground">
              Detected fields are filled in. Complete any empty details, then save.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded-sm opacity-70 hover:opacity-100 transition-opacity disabled:pointer-events-none"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="vendor-registration-dialog__body">
          <VendorDetailPanel
            vendor={draft}
            onChange={(patch) => setDraft((prev) => (prev ? { ...prev, ...patch } : prev))}
            masked={bankMasked}
            onToggleMask={() => setBankMasked((value) => !value)}
            showConfirmation={false}
            className="bg-transparent p-0"
          />
        </div>

        <div className="vendor-registration-dialog__footer">
          <Button type="button" variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="button"
            disabled={saving || !draft.name.trim()}
            onClick={() => onSave(draft)}
            data-testid="save-complete-vendor-registration"
          >
            <ClipboardCheck className="h-4 w-4 mr-1" />
            {saving ? "Saving…" : "Save vendor"}
          </Button>
        </div>
      </div>
    </div>
  );
}
