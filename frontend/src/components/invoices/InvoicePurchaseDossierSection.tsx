import { Link } from "react-router-dom";
import { PurchaseDetailContent } from "@/components/purchases/PurchaseDetailPanel";
import type { PurchaseDossier } from "@/api/types";
import { purchaseDetailFromDossier, type PurchaseDossierWithSummary } from "@/lib/purchaseDossierDetail";

type InvoicePurchaseDossierSectionProps = {
  dossier: PurchaseDossier | null;
  loading: boolean;
  vendor?: string;
  item?: string;
  onOpenSibling?: (invoiceId: number) => void;
};

export function InvoicePurchaseDossierSection({
  dossier,
  loading,
  vendor,
  item,
  onOpenSibling,
}: InvoicePurchaseDossierSectionProps) {
  if (loading) {
    return <p className="mt-4 text-sm text-muted-foreground">Loading purchase dossier…</p>;
  }

  if (!dossier?.po_reference) {
    return (
      <div className="mt-4 rounded-md border border-dashed border-border p-6 text-center">
        <p className="text-sm font-medium">No purchase order linked</p>
        <p className="text-xs text-muted-foreground mt-1">
          Upload PO / GRN documents on the same PO reference, or open the row in Purchase Management
          for three-way match.
        </p>
        <Link to="/purchases" className="inline-block mt-3 text-xs text-primary hover:underline">
          Open Purchase Management →
        </Link>
      </div>
    );
  }

  const detail = purchaseDetailFromDossier(dossier as PurchaseDossierWithSummary, {
    vendor: vendor ?? "—",
    item: item ?? "—",
  });

  if (!detail) {
    return (
      <div className="mt-4 rounded-md border border-dashed border-border p-6 text-center">
        <p className="text-sm font-medium">Purchase register not linked yet</p>
        <p className="text-xs text-muted-foreground mt-1 tnum">{dossier.po_reference}</p>
        <Link to="/purchases" className="inline-block mt-3 text-xs text-primary hover:underline">
          Open Purchase Management →
        </Link>
      </div>
    );
  }

  const { po, m, invoiceId } = detail;

  return (
    <div className="mt-2">
      <PurchaseDetailContent
        po={po}
        match={m}
        invoiceId={invoiceId}
        canApproveVariance={false}
        onApprove={() => undefined}
        onOpenInvoice={
          invoiceId != null && onOpenSibling ? () => onOpenSibling(invoiceId) : undefined
        }
        onOpenPoDocument={
          po.poDocumentId != null && onOpenSibling
            ? () => onOpenSibling(po.poDocumentId!)
            : undefined
        }
        onOpenGrnDocument={
          po.grnDocumentId != null && onOpenSibling
            ? () => onOpenSibling(po.grnDocumentId!)
            : undefined
        }
      />
      {dossier.purchase_order_id != null ? (
        <Link to="/purchases" className="inline-block mt-3 text-xs text-primary hover:underline">
          Approve variance or record GRN in Purchase Management →
        </Link>
      ) : null}
    </div>
  );
}
