import type { SalesDossierResponse, SalesOrderApi, ThreeWayMatchApi } from "@/api/types";
import { apiSalesToRow, mapThreeWayMatchFromApi } from "@/lib/routePageAdapters";
import type { SalesOrder, ThreeWayMatch, MatchStatus } from "@/lib/v4MockData";

export type SalesDossierWithSummary = SalesDossierResponse & {
  sales_register?: SalesOrderApi | null;
};

function memberInvoiceId(dossier: SalesDossierResponse, role: string): number | null {
  const row = dossier.members.find((m) => m.role === role);
  return row?.invoice_id ?? null;
}

export function salesDetailFromDossier(
  dossier: SalesDossierWithSummary,
  options: { customer?: string; item?: string; requestor?: string } = {}
): { so: SalesOrder; m: ThreeWayMatch; invoiceId: number | null } | null {
  if (dossier.sales_register) {
    const row = apiSalesToRow(dossier.sales_register);
    return { so: row.so, m: row.m, invoiceId: row.invoiceId };
  }

  const customer = options.customer ?? "—";
  const item = options.item ?? "—";
  const requestor = options.requestor ?? "—";
  const match: ThreeWayMatchApi | null = dossier.match;
  const summary = dossier.match_summary;
  if (!match || !dossier.so_reference) return null;

  const soQty = summary?.po_qty ?? 0;
  const soUnitPrice = summary?.po_unit_price ?? 0;
  const invoiceQty = summary?.invoice_qty ?? 0;
  const invoiceUnitPrice = summary?.invoice_unit_price ?? 0;
  const dnPresent = summary?.grn_present ?? dossier.members.some((m) => m.role === "dn" && m.present);

  const so: SalesOrder = {
    id: summary?.po_number ?? dossier.so_reference,
    customer,
    date: summary?.po_date ?? "—",
    requestor,
    item,
    soQty,
    soUnitPrice,
    dnQty: dnPresent ? (summary?.grn_qty ?? null) : null,
    dnDate: summary?.grn_date ?? null,
    dnShipper: summary?.grn_receiver ?? null,
    dnCondition: summary?.grn_condition ?? null,
    invoiceNo: summary?.invoice_no ?? "—",
    invoiceQty,
    invoiceUnitPrice,
    gstRate:
      summary?.invoice_value && summary.invoice_gst
        ? summary.invoice_gst / summary.invoice_value
        : 0.1,
    routedForApproval: false,
    soDocumentId: memberInvoiceId(dossier, "so"),
    dnDocumentId: memberInvoiceId(dossier, "dn"),
  };

  const m: ThreeWayMatch = {
    ...mapThreeWayMatchFromApi(match),
    status: (dossier.match_status ?? match.status) as MatchStatus,
  };

  const invoiceId = memberInvoiceId(dossier, "invoice");
  return { so, m, invoiceId };
}
