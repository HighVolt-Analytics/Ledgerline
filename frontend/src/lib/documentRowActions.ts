import type { Invoice } from "@/api/types";
import { requiresClassificationConfirm } from "@/lib/classificationAuditDisplay";
import { storedDocumentTypeCode } from "@/lib/documentTypeResolve";
import {
  ROUTE_EXPENSES,
  ROUTE_PURCHASE,
  ROUTE_SALES,
  ROUTE_TEAM,
} from "@/lib/invoice";
import {
  canApproveFromDrawer,
  canRejectClaim,
  invoiceHasApprovableSource,
  validateInvoiceReadyForApproval,
} from "@/lib/invoiceActions";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

export type DocumentRowActionKind = "classify" | "match" | "approve" | "reject" | "none";

/** Drawer tabs the Upload row chip may open. */
export type DocumentRowDrawerTab = "fields" | "po";

export type DocumentRowAction = {
  kind: DocumentRowActionKind;
  label: string;
  /** When set, chip opens the drawer on this tab instead of mutating. */
  drawerTab?: DocumentRowDrawerTab;
};

export type DocumentRowActionsResult = {
  primary: DocumentRowAction;
  overflow: DocumentRowAction[];
};

const MATCH_PURCHASE_TYPES = new Set(["po", "grn"]);
const MATCH_SALES_TYPES = new Set(["so", "dn"]);

function routeOf(inv: Pick<Invoice, "route_target">): string {
  return (inv.route_target ?? "").trim();
}

function needsClassification(inv: Invoice): boolean {
  if (!storedDocumentTypeCode(inv)) return true;
  return requiresClassificationConfirm(inv);
}

function isPurchaseOrSalesRoute(route: string): boolean {
  return route === ROUTE_PURCHASE || route === ROUTE_SALES;
}

function needsMatch(inv: Invoice): boolean {
  const route = routeOf(inv);
  if (!isPurchaseOrSalesRoute(route)) return false;
  const evalStatus = (inv.evaluation_status ?? "").trim();
  if (evalStatus === "awaiting_po" || evalStatus === "awaiting_so") return true;
  if (evalStatus === "needs_review") return true;

  if (route === ROUTE_PURCHASE) {
    const kind = (inv.purchase_document_type ?? "").trim().toLowerCase();
    if (MATCH_PURCHASE_TYPES.has(kind)) return true;
    // Commercial invoice without PO reference still needs the Match continuum.
    if (!kind || kind === "invoice") {
      return !(inv.po_reference ?? "").trim();
    }
    return false;
  }

  const kind = (inv.sales_document_type ?? "").trim().toLowerCase();
  if (MATCH_SALES_TYPES.has(kind)) return true;
  if (!kind || kind === "invoice") {
    return !(inv.so_reference ?? "").trim();
  }
  return false;
}

function canOneClickApprove(
  inv: Invoice,
  documentTypes: DocumentTypeDefinition[] | undefined
): boolean {
  if (!canApproveFromDrawer(inv)) return false;
  if (!invoiceHasApprovableSource(inv)) return false;
  if (documentTypes === undefined) {
    // Without catalogue, still require positive amount on claim expense routes.
    const route = routeOf(inv);
    if (route === ROUTE_TEAM || route === ROUTE_EXPENSES) {
      const raw = String(inv.total ?? "").trim();
      const n = Number(raw);
      return Boolean(raw && !Number.isNaN(n) && n > 0);
    }
    return true;
  }
  return validateInvoiceReadyForApproval(inv, documentTypes).ok;
}

/**
 * Primary + overflow chips for an Upload document row.
 * Priority: Classify > Match > Approve > Reject (overflow when Approve is primary).
 * Never offers one-click Approve that cannot complete.
 */
export function documentRowActions(
  inv: Invoice,
  documentTypes?: DocumentTypeDefinition[] | undefined
): DocumentRowActionsResult {
  if (needsClassification(inv)) {
    const overflow: DocumentRowAction[] = [];
    if (canRejectClaim(inv.status)) {
      overflow.push({ kind: "reject", label: "Reject" });
    }
    return {
      primary: { kind: "classify", label: "Classify", drawerTab: "fields" },
      overflow,
    };
  }

  if (needsMatch(inv)) {
    const overflow: DocumentRowAction[] = [];
    if (canRejectClaim(inv.status)) {
      overflow.push({ kind: "reject", label: "Reject" });
    }
    return {
      primary: { kind: "match", label: "Match", drawerTab: "po" },
      overflow,
    };
  }

  if (canOneClickApprove(inv, documentTypes)) {
    const overflow: DocumentRowAction[] = [];
    if (canRejectClaim(inv.status)) {
      overflow.push({ kind: "reject", label: "Reject" });
    }
    return {
      primary: { kind: "approve", label: "Approve" },
      overflow,
    };
  }

  if (canRejectClaim(inv.status)) {
    return {
      primary: { kind: "reject", label: "Reject" },
      overflow: [],
    };
  }

  return {
    primary: { kind: "none", label: "" },
    overflow: [],
  };
}

/** Honest-gap: budget bar only when allocated is a positive configured amount. */
export function budgetUtilizationDisplay(
  allocated: number | null | undefined,
  consumed: number | null | undefined
):
  | { kind: "configured"; used: number; total: number; pct: number }
  | { kind: "missing"; message: string } {
  const total = Number(allocated);
  if (!Number.isFinite(total) || total <= 0) {
    return { kind: "missing", message: "No budget configured" };
  }
  const used = Number.isFinite(Number(consumed)) ? Math.max(0, Number(consumed)) : 0;
  const pct = Math.min(100, Math.round((used / total) * 100));
  return { kind: "configured", used, total, pct };
}

/**
 * Advance display: unmatched / unknown balance → gap copy.
 * Confirmed 0 on a matched employee is a real number.
 * With float + remaining, fill = consumed (float − remaining) / float.
 */
export function advanceBalanceDisplay(
  matched: boolean,
  advanceBalance: number | null | undefined,
  advanceFloat?: number | null | undefined
):
  | { kind: "remaining"; remaining: number }
  | { kind: "consumed"; used: number; total: number; pct: number; remaining: number }
  | { kind: "missing"; message: string } {
  if (!matched) {
    return { kind: "missing", message: "No advance on file" };
  }
  if (advanceBalance == null || !Number.isFinite(Number(advanceBalance))) {
    return { kind: "missing", message: "No advance on file" };
  }
  const remaining = Math.max(0, Number(advanceBalance));
  const float = Number(advanceFloat);
  if (Number.isFinite(float) && float > 0) {
    const used = Math.max(0, float - remaining);
    const pct = Math.min(100, Math.round((used / float) * 100));
    return { kind: "consumed", used, total: float, pct, remaining };
  }
  return { kind: "remaining", remaining };
}

export function isClaimExpenseRoute(route: string | null | undefined): boolean {
  const r = (route ?? "").trim();
  return r === ROUTE_TEAM || r === ROUTE_EXPENSES;
}

export function isMatchRoute(route: string | null | undefined): boolean {
  const r = (route ?? "").trim();
  return r === ROUTE_PURCHASE || r === ROUTE_SALES;
}
