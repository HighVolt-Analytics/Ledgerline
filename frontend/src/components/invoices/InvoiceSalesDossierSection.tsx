import { Link } from "react-router-dom";
import { SalesDetailContent } from "@/components/sales/SalesDetailPanel";
import type { SalesDossierResponse } from "@/api/types";
import { salesDetailFromDossier, type SalesDossierWithSummary } from "@/lib/salesDossierDetail";

type InvoiceSalesDossierSectionProps = {
  dossier: SalesDossierResponse | null;
  loading: boolean;
  customer?: string;
  item?: string;
  onOpenSibling?: (invoiceId: number) => void;
};

export function InvoiceSalesDossierSection({
  dossier,
  loading,
  customer,
  item,
  onOpenSibling,
}: InvoiceSalesDossierSectionProps) {
  if (loading) {
    return <p className="mt-4 text-sm text-muted-foreground">Loading sales dossier…</p>;
  }

  if (!dossier?.so_reference) {
    return (
      <div className="mt-4 rounded-md border border-dashed border-border p-6 text-center">
        <p className="text-sm font-medium">No sales order linked</p>
        <p className="text-xs text-muted-foreground mt-1">
          Upload SO / DN documents on the same SO reference, or open the row in Sales Management for
          three-way match.
        </p>
        <Link to="/sales" className="inline-block mt-3 text-xs text-primary hover:underline">
          Open Sales Management →
        </Link>
      </div>
    );
  }

  const detail = salesDetailFromDossier(dossier as SalesDossierWithSummary, {
    customer: customer ?? "—",
    item: item ?? "—",
  });

  if (!detail) {
    return (
      <div className="mt-4 rounded-md border border-dashed border-border p-6 text-center">
        <p className="text-sm font-medium">Sales register not linked yet</p>
        <p className="text-xs text-muted-foreground mt-1 tnum">{dossier.so_reference}</p>
        <Link to="/sales" className="inline-block mt-3 text-xs text-primary hover:underline">
          Open Sales Management →
        </Link>
      </div>
    );
  }

  const { so, m, invoiceId } = detail;

  return (
    <div className="mt-2">
      <SalesDetailContent
        so={so}
        match={m}
        invoiceId={invoiceId}
        canApproveVariance={false}
        onApprove={() => undefined}
        onOpenInvoice={
          invoiceId != null && onOpenSibling ? () => onOpenSibling(invoiceId) : undefined
        }
        onOpenSoDocument={
          so.soDocumentId != null && onOpenSibling
            ? () => onOpenSibling(so.soDocumentId!)
            : undefined
        }
        onOpenDnDocument={
          so.dnDocumentId != null && onOpenSibling
            ? () => onOpenSibling(so.dnDocumentId!)
            : undefined
        }
      />
      {dossier.sales_order_id != null ? (
        <Link to="/sales" className="inline-block mt-3 text-xs text-primary hover:underline">
          Approve variance or record DN in Sales Management →
        </Link>
      ) : null}
    </div>
  );
}
