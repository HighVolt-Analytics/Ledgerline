import { useCallback } from "react";
import { SalesDetailContent } from "@/components/sales/SalesDetailPanel";
import type { SalesDossierResponse } from "@/api/types";
import { useSalesMutations } from "@/hooks/useSalesMutations";
import { salesDetailFromDossier, type SalesDossierWithSummary } from "@/lib/salesDossierDetail";
import { matchTabLabel } from "@/lib/documentPlaybookConfig";
import { isSalesManagementRoute } from "@/lib/documentBundleConfig";

type InvoiceSalesDossierSectionProps = {
  dossier: SalesDossierResponse | null;
  loading: boolean;
  customer?: string;
  item?: string;
  twoWay?: boolean;
  routeTarget?: string | null;
  onOpenSibling?: (invoiceId: number) => void;
  onMutated?: () => void;
};

export function InvoiceSalesDossierSection({
  dossier,
  loading,
  customer,
  item,
  twoWay = false,
  routeTarget,
  onOpenSibling,
  onMutated,
}: InvoiceSalesDossierSectionProps) {
  const mutations = useSalesMutations();
  const matchLabel = matchTabLabel(routeTarget ?? "Sales Management", twoWay ? "two_way_dn_invoice" : "three_way_so_dn");

  const reloadAfterMutation = useCallback(async () => {
    onMutated?.();
  }, [onMutated]);

  if (loading) {
    return <p className="mt-4 text-sm text-muted-foreground">Loading sales dossier…</p>;
  }

  if (!dossier?.so_reference) {
    return (
      <div className="mt-4 rounded-md border border-dashed border-border p-6 text-center">
        <p className="text-sm font-medium">No sales order linked</p>
        <p className="text-xs text-muted-foreground mt-1">
          {twoWay
            ? "2-way DN match needs an SO reference and a delivery note on the same order."
            : "Upload SO and DN documents on the same SO reference for 3-way match."}
        </p>
        {isSalesManagementRoute(routeTarget) ? (
          <p className="text-xs text-muted-foreground mt-2">
            Tab: <span className="font-medium text-foreground">{matchLabel}</span>
          </p>
        ) : null}
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
        <p className="text-xs text-muted-foreground mt-2">
          Upload a classified SO copy on this reference, or record a delivery note once the register exists.
        </p>
      </div>
    );
  }

  const { so, m, invoiceId } = detail;
  const salesOrderId = dossier.sales_order_id;
  const busy = salesOrderId != null && mutations.busyId === salesOrderId;
  const canAct = salesOrderId != null;

  return (
    <div className="mt-2">
      {mutations.toast ? (
        <p className="mb-2 text-xs text-muted-foreground">{mutations.toast}</p>
      ) : null}
      <SalesDetailContent
        so={so}
        match={m}
        invoiceId={invoiceId}
        busy={busy}
        canApproveVariance={Boolean(canAct && so.routedForApproval)}
        onApprove={async () => {
          if (salesOrderId == null) return;
          await mutations.approveVariance(salesOrderId);
          await reloadAfterMutation();
        }}
        onRecordDn={
          canAct
            ? async (body) => {
                if (salesOrderId == null) return;
                await mutations.recordDeliveryNote(salesOrderId, body);
                await reloadAfterMutation();
              }
            : undefined
        }
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
    </div>
  );
}
