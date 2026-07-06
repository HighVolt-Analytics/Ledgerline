import { useCallback } from "react";
import { PurchaseDetailContent } from "@/components/purchases/PurchaseDetailPanel";
import type { PurchaseDossier } from "@/api/types";
import { usePurchaseMutations } from "@/hooks/usePurchaseMutations";
import { purchaseDetailFromDossier, type PurchaseDossierWithSummary } from "@/lib/purchaseDossierDetail";
import { matchTabLabel } from "@/lib/documentPlaybookConfig";
import { isPurchaseManagementRoute } from "@/lib/documentBundleConfig";

type InvoicePurchaseDossierSectionProps = {
  dossier: PurchaseDossier | null;
  loading: boolean;
  vendor?: string;
  item?: string;
  twoWay?: boolean;
  routeTarget?: string | null;
  onOpenSibling?: (invoiceId: number) => void;
  onMutated?: () => void;
};

export function InvoicePurchaseDossierSection({
  dossier,
  loading,
  vendor,
  item,
  twoWay = false,
  routeTarget,
  onOpenSibling,
  onMutated,
}: InvoicePurchaseDossierSectionProps) {
  const mutations = usePurchaseMutations();
  const matchLabel = matchTabLabel(routeTarget ?? "Purchase Management", twoWay ? "two_way_po_ses" : "three_way_po_grn");

  const reloadAfterMutation = useCallback(async () => {
    onMutated?.();
  }, [onMutated]);

  if (loading) {
    return <p className="mt-4 text-sm text-muted-foreground">Loading purchase dossier…</p>;
  }

  if (!dossier?.po_reference) {
    return (
      <div className="mt-4 rounded-md border border-dashed border-border p-6 text-center">
        <p className="text-sm font-medium">No purchase order linked</p>
        <p className="text-xs text-muted-foreground mt-1">
          {twoWay
            ? "2-way service-entry match needs a PO reference and service entry evidence on the same PO."
            : "Upload PO and GRN documents on the same PO reference for 3-way match."}
        </p>
        {isPurchaseManagementRoute(routeTarget) ? (
          <p className="text-xs text-muted-foreground mt-2">
            Tab: <span className="font-medium text-foreground">{matchLabel}</span>
          </p>
        ) : null}
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
        <p className="text-xs text-muted-foreground mt-2">
          Upload a classified PO copy on this reference, or record a GRN below once the register exists.
        </p>
      </div>
    );
  }

  const { po, m, invoiceId } = detail;
  const purchaseOrderId = dossier.purchase_order_id;
  const busy = purchaseOrderId != null && mutations.busyId === purchaseOrderId;
  const canAct = purchaseOrderId != null;

  return (
    <div className="mt-2">
      {mutations.toast ? (
        <p className="mb-2 text-xs text-muted-foreground">{mutations.toast}</p>
      ) : null}
      <PurchaseDetailContent
        po={po}
        match={m}
        invoiceId={invoiceId}
        busy={busy}
        canApproveVariance={Boolean(canAct && po.routedForApproval)}
        onApprove={async () => {
          if (purchaseOrderId == null) return;
          await mutations.approveVariance(purchaseOrderId);
          await reloadAfterMutation();
        }}
        onRecordGrn={
          canAct
            ? async (body) => {
                if (purchaseOrderId == null) return;
                await mutations.recordGrn(purchaseOrderId, body);
                await reloadAfterMutation();
              }
            : undefined
        }
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
    </div>
  );
}
