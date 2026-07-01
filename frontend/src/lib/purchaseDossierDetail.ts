import type { PurchaseDossier, PurchaseOrderApi, ThreeWayMatchApi } from "@/api/types";
import { apiPurchaseToRow, mapThreeWayMatchFromApi } from "@/lib/routePageAdapters";
import type { PurchaseOrder, ThreeWayMatch, MatchStatus } from "@/lib/v4MockData";

export type PurchaseDossierMatchSummary = {
  status: string;
  currency: string;
  po_number?: string | null;
  po_qty?: number | null;
  po_unit_price?: number | null;
  po_value: number;
  po_date?: string | null;
  grn_present?: boolean;
  grn_qty?: number | null;
  grn_date?: string | null;
  grn_receiver?: string | null;
  grn_condition?: string | null;
  invoice_no?: string | null;
  invoice_qty?: number | null;
  invoice_unit_price?: number | null;
  invoice_value?: number;
  invoice_gst?: number;
  invoice_total: number;
  qty_variance_value?: number;
  price_variance_value?: number;
  total_deviation?: number;
};

export type PurchaseDossierWithSummary = PurchaseDossier & {
  match_summary?: PurchaseDossierMatchSummary | null;
  purchase_register?: PurchaseOrderApi | null;
};

function memberInvoiceId(dossier: PurchaseDossier, role: string): number | null {
  const row = dossier.members.find((m) => m.role === role);
  return row?.invoice_id ?? null;
}

export function purchaseDetailFromDossier(
  dossier: PurchaseDossierWithSummary,
  options: { vendor?: string; item?: string; requestor?: string } = {},
): { po: PurchaseOrder; m: ThreeWayMatch; invoiceId: number | null } | null {
  if (dossier.purchase_register) {
    const row = apiPurchaseToRow(dossier.purchase_register);
    return { po: row.po, m: row.m, invoiceId: row.invoiceId };
  }

  const vendor = options.vendor ?? "—";
  const item = options.item ?? "—";
  const requestor = options.requestor ?? "—";
  const match: ThreeWayMatchApi | null = dossier.match;
  const summary = dossier.match_summary;
  if (!match || !dossier.po_reference) return null;

  const poQty = summary?.po_qty ?? 0;
  const poUnitPrice = summary?.po_unit_price ?? 0;
  const invoiceQty = summary?.invoice_qty ?? 0;
  const invoiceUnitPrice = summary?.invoice_unit_price ?? 0;
  const grnPresent = summary?.grn_present ?? dossier.members.some((m) => m.role === "grn" && m.present);

  const po: PurchaseOrder = {
    id: summary?.po_number ?? dossier.po_reference,
    vendor,
    date: summary?.po_date ?? "—",
    requestor,
    item,
    poQty,
    poUnitPrice,
    grnQty: grnPresent ? (summary?.grn_qty ?? null) : null,
    grnDate: summary?.grn_date ?? null,
    grnReceiver: summary?.grn_receiver ?? null,
    grnCondition: summary?.grn_condition ?? null,
    invoiceNo: summary?.invoice_no ?? "—",
    invoiceQty,
    invoiceUnitPrice,
    gstRate:
      summary?.invoice_value && summary.invoice_gst
        ? summary.invoice_gst / summary.invoice_value
        : 0.1,
    routedForApproval: false,
    poDocumentId: memberInvoiceId(dossier, "po"),
    grnDocumentId: memberInvoiceId(dossier, "grn"),
  };

  const m: ThreeWayMatch = {
    ...mapThreeWayMatchFromApi(match),
    status: (dossier.match_status ?? match.status) as MatchStatus,
  };

  const invoiceId = memberInvoiceId(dossier, "invoice");
  return { po, m, invoiceId };
}
