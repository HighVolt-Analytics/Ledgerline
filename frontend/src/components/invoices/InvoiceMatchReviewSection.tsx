import { Check, Link2 } from "lucide-react";
import type { Invoice, PurchaseDossier, SalesDossierResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  purchaseDetailFromDossier,
  type PurchaseDossierWithSummary,
} from "@/lib/purchaseDossierDetail";
import {
  salesDetailFromDossier,
  type SalesDossierWithSummary,
} from "@/lib/salesDossierDetail";
import { ROUTE_PURCHASE, ROUTE_SALES } from "@/lib/invoice";

export type MatchReviewSummary = {
  headline: string;
  detail?: string;
  canApproveVariance: boolean;
  needsReceiptRecord: boolean;
  receiptLabel: "GRN" | "DN" | null;
  orderId: number | null;
  cleanMatch: boolean;
};

export function summarizePurchaseMatchReview(
  inv: Invoice,
  dossier: PurchaseDossier | null,
  loading: boolean
): MatchReviewSummary {
  const evalStatus = (inv.evaluation_status ?? "").trim();
  const poRef = (inv.po_reference ?? "").trim();
  const hint = (inv.resolution_hint ?? "").trim();

  if (loading) {
    return {
      headline: "Loading match…",
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId: null,
      cleanMatch: false,
    };
  }

  if (evalStatus === "awaiting_po") {
    return {
      headline: poRef ? `Awaiting PO ${poRef}` : "Awaiting purchase order document",
      detail: hint || undefined,
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId: null,
      cleanMatch: false,
    };
  }

  if (!poRef) {
    return {
      headline: "Missing PO reference",
      detail: hint || "Add a PO reference on Fields, then open Match.",
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId: null,
      cleanMatch: false,
    };
  }

  if (!dossier?.po_reference) {
    return {
      headline: `PO ${poRef} — no match yet`,
      detail: hint || "Open Match to link PO / GRN / Invoice on this reference.",
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId: dossier?.purchase_order_id ?? null,
      cleanMatch: false,
    };
  }

  const detail = purchaseDetailFromDossier(dossier as PurchaseDossierWithSummary, {
    vendor: inv.vendor ?? undefined,
  });
  const orderId = dossier.purchase_order_id;
  if (!detail) {
    return {
      headline: `PO ${poRef}`,
      detail: hint || "Upload a classified PO copy, or record a GRN once the register exists.",
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId,
      cleanMatch: false,
    };
  }

  const { po, m } = detail;
  if (po.routedForApproval && orderId != null) {
    return {
      headline: "Variance awaiting approval",
      detail: `${m.status} · ${poRef}`,
      canApproveVariance: true,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId,
      cleanMatch: false,
    };
  }
  if (po.grnQty === null && orderId != null) {
    return {
      headline: "GRN not recorded",
      detail: `PO ${poRef} — record goods receipt on the Match tab.`,
      canApproveVariance: false,
      needsReceiptRecord: true,
      receiptLabel: "GRN",
      orderId,
      cleanMatch: false,
    };
  }
  if (m.status === "3-Way Match" || m.status === "2-Way Match") {
    return {
      headline: m.status,
      detail: `PO ${poRef}`,
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId,
      cleanMatch: true,
    };
  }
  return {
    headline: m.status.replace(/_/g, " "),
    detail: hint || `PO ${poRef}`,
    canApproveVariance: false,
    needsReceiptRecord: false,
    receiptLabel: null,
    orderId,
    cleanMatch: false,
  };
}

export function summarizeSalesMatchReview(
  inv: Invoice,
  dossier: SalesDossierResponse | null,
  loading: boolean
): MatchReviewSummary {
  const evalStatus = (inv.evaluation_status ?? "").trim();
  const soRef = (inv.so_reference ?? "").trim();
  const hint = (inv.resolution_hint ?? "").trim();

  if (loading) {
    return {
      headline: "Loading match…",
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId: null,
      cleanMatch: false,
    };
  }

  if (evalStatus === "awaiting_so") {
    return {
      headline: soRef ? `Awaiting SO ${soRef}` : "Awaiting sales order document",
      detail: hint || undefined,
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId: null,
      cleanMatch: false,
    };
  }

  if (!soRef) {
    return {
      headline: "Missing SO reference",
      detail: hint || "Add an SO reference on Fields, then open Match.",
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId: null,
      cleanMatch: false,
    };
  }

  if (!dossier?.so_reference) {
    return {
      headline: `SO ${soRef} — no match yet`,
      detail: hint || "Open Match to link SO / DN / Invoice on this reference.",
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId: dossier?.sales_order_id ?? null,
      cleanMatch: false,
    };
  }

  const detail = salesDetailFromDossier(dossier as SalesDossierWithSummary, {
    customer: inv.vendor ?? undefined,
  });
  const orderId = dossier.sales_order_id;
  if (!detail) {
    return {
      headline: `SO ${soRef}`,
      detail: hint || "Upload supporting documents on this SO reference.",
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId,
      cleanMatch: false,
    };
  }

  const { so, m } = detail;
  if (so.routedForApproval && orderId != null) {
    return {
      headline: "Variance awaiting approval",
      detail: `${m.status} · ${soRef}`,
      canApproveVariance: true,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId,
      cleanMatch: false,
    };
  }
  if (so.dnQty === null && orderId != null) {
    return {
      headline: "DN not recorded",
      detail: `SO ${soRef} — record delivery note on the Match tab.`,
      canApproveVariance: false,
      needsReceiptRecord: true,
      receiptLabel: "DN",
      orderId,
      cleanMatch: false,
    };
  }
  if (m.status === "3-Way Match" || m.status === "2-Way Match") {
    return {
      headline: m.status,
      detail: `SO ${soRef}`,
      canApproveVariance: false,
      needsReceiptRecord: false,
      receiptLabel: null,
      orderId,
      cleanMatch: true,
    };
  }
  return {
    headline: m.status.replace(/_/g, " "),
    detail: hint || `SO ${soRef}`,
    canApproveVariance: false,
    needsReceiptRecord: false,
    receiptLabel: null,
    orderId,
    cleanMatch: false,
  };
}

export function InvoiceMatchReviewSection({
  inv,
  purchaseDossier,
  salesDossier,
  loading,
  busy = false,
  onOpenMatch,
  onApproveVariance,
}: {
  inv: Invoice;
  purchaseDossier: PurchaseDossier | null;
  salesDossier: SalesDossierResponse | null;
  loading: boolean;
  busy?: boolean;
  onOpenMatch: () => void;
  onApproveVariance?: () => void | Promise<void>;
}) {
  const route = (inv.route_target ?? "").trim();
  const isSales = route === ROUTE_SALES || route.toLowerCase().includes("sales");
  const summary = isSales
    ? summarizeSalesMatchReview(inv, salesDossier, loading)
    : summarizePurchaseMatchReview(inv, purchaseDossier, loading);

  const sideLabel = route === ROUTE_PURCHASE || route === ROUTE_SALES ? route : "Match";

  return (
    <Card className="p-3 mt-4 space-y-3" data-testid="invoice-match-review">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] text-muted-foreground uppercase tracking-wide">
            {sideLabel}
          </div>
          <div className="text-sm font-medium mt-0.5">{summary.headline}</div>
          {summary.detail ? (
            <p className="text-xs text-muted-foreground mt-1">{summary.detail}</p>
          ) : null}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button
          type="button"
          size="sm"
          variant="outline"
          onClick={onOpenMatch}
          data-testid="button-open-match-tab"
        >
          <Link2 className="h-4 w-4 mr-1" />
          Open Match
        </Button>
        {summary.canApproveVariance && onApproveVariance ? (
          <Button
            type="button"
            size="sm"
            disabled={busy}
            onClick={() => void onApproveVariance()}
            data-testid="button-approve-variance-fields"
          >
            <Check className="h-4 w-4 mr-1" />
            Approve variance
          </Button>
        ) : null}
        {summary.needsReceiptRecord && summary.receiptLabel ? (
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={onOpenMatch}
            data-testid="button-record-receipt-fields"
          >
            Record {summary.receiptLabel}
          </Button>
        ) : null}
      </div>
    </Card>
  );
}
