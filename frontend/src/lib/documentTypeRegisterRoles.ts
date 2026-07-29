/**
 * Org DT → purchase/sales register roles (mirrors backend document_type_register_roles).
 *
 * Supporting bundle schema roles stay po|grn / so|dn.
 * Commercial invoice legs come from po_goods / ar_goods playbooks — not an invoice bundleRole.
 */

import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";
import { isTransPosting } from "@/lib/documentTypeKlass";

export type RegisterSide = "purchase" | "sales";
export type PurchaseRegisterRole = "po" | "grn" | "invoice";
export type SalesRegisterRole = "so" | "dn" | "invoice";

const AR_GOODS = new Set(["ar_goods", "ar_goods_2way"]);
const PO_GOODS = new Set(["po_goods"]);

const PURCHASE_FALLBACK: Record<string, { code: string; label: string }> = {
  po: { code: "DT-02", label: "Purchase order" },
  grn: { code: "DT-03", label: "Goods receipt" },
  invoice: { code: "DT-01", label: "Commercial invoice" },
};

const SALES_FALLBACK: Record<string, { code: string; label: string }> = {
  so: { code: "DT-27", label: "Sales order" },
  dn: { code: "DT-28", label: "Delivery note" },
  invoice: { code: "DT-26", label: "Customer invoice" },
};

function labelOf(dt: DocumentTypeDefinition): string {
  return `${dt.shortTitle || ""} ${dt.title || ""}`.toLowerCase();
}

function playbookProfile(dt: DocumentTypeDefinition): string {
  return (dt.playbookProfile || "").trim().toLowerCase();
}

export function inferPurchaseSupportingRole(dt: DocumentTypeDefinition | null | undefined): string {
  if (!dt) return "";
  const explicit = (dt.purchaseBundleRole || "").trim().toLowerCase();
  if (explicit === "po" || explicit === "grn") return explicit;
  const salesExplicit = (dt.salesBundleRole || "").trim().toLowerCase();
  if (salesExplicit === "so" || salesExplicit === "dn") return "";
  const label = labelOf(dt);
  if (
    ["grn", "goods receipt", "delivery receipt", "proof of delivery", "receipt note"].some((t) =>
      label.includes(t)
    )
  ) {
    return "grn";
  }
  if (label.includes("invoice") || label.includes("tax inv")) return "";
  if (label.includes("purchase order")) return "po";
  if (/\bpo\s*(copy|\(|document|form)\b/.test(label)) return "po";
  const short = (dt.shortTitle || "").trim().toLowerCase();
  if (short === "po" || short === "p.o." || short === "p.o") return "po";
  return "";
}

export function inferSalesSupportingRole(dt: DocumentTypeDefinition | null | undefined): string {
  if (!dt) return "";
  const explicit = (dt.salesBundleRole || "").trim().toLowerCase();
  if (explicit === "so" || explicit === "dn") return explicit;
  const label = labelOf(dt);
  if (["delivery note", "dispatch", "dn "].some((t) => label.includes(t))) return "dn";
  if (["sales order", "so ", "so-"].some((t) => label.includes(t))) return "so";
  return "";
}

export function purchaseRegisterRoleForDefinition(
  dt: DocumentTypeDefinition | null | undefined
): string {
  if (!dt) return "";
  const supporting = inferPurchaseSupportingRole(dt);
  if (supporting) return supporting;
  const profile = playbookProfile(dt);
  if (PO_GOODS.has(profile)) return "invoice";
  if (
    dt.routeTarget === "Purchase Management" &&
    isTransPosting(dt) &&
    profile !== "supporting" &&
    profile !== "direct_expense"
  ) {
    const label = labelOf(dt);
    if (
      [
        "commercial invoice",
        "tax invoice",
        "vendor invoice",
        "supplier invoice",
        "purchase invoice",
        "non-po vendor",
        "non po vendor",
      ].some((t) => label.includes(t))
    ) {
      return "invoice";
    }
  }
  return "";
}

export function salesRegisterRoleForDefinition(
  dt: DocumentTypeDefinition | null | undefined
): string {
  if (!dt) return "";
  const supporting = inferSalesSupportingRole(dt);
  if (supporting) return supporting;
  const profile = playbookProfile(dt);
  if (AR_GOODS.has(profile)) return "invoice";
  if (dt.routeTarget === "Sales Management" && isTransPosting(dt) && profile !== "supporting") {
    const label = labelOf(dt);
    if (
      [
        "customer invoice",
        "customer tax",
        "tax invoice",
        "sales invoice",
        "ar invoice",
        "commercial invoice",
      ].some((t) => label.includes(t))
    ) {
      return "invoice";
    }
  }
  return "";
}

export function registerRoleForDefinition(
  dt: DocumentTypeDefinition | null | undefined,
  side: RegisterSide
): string {
  return side === "purchase"
    ? purchaseRegisterRoleForDefinition(dt)
    : salesRegisterRoleForDefinition(dt);
}

function commercialDefinitions(
  documentTypes: DocumentTypeDefinition[],
  side: RegisterSide
): DocumentTypeDefinition[] {
  const out: DocumentTypeDefinition[] = [];
  const seen = new Set<string>();
  for (const row of documentTypes) {
    if (!row.enabled) continue;
    if (registerRoleForDefinition(row, side) !== "invoice") continue;
    const code = (row.code || "").trim().toUpperCase();
    if (!code || seen.has(code)) continue;
    seen.add(code);
    out.push(row);
  }
  return out;
}

export function purchaseCommercialInvoiceDefinitions(
  documentTypes: DocumentTypeDefinition[]
): DocumentTypeDefinition[] {
  return commercialDefinitions(documentTypes, "purchase");
}

export function salesCommercialInvoiceDefinitions(
  documentTypes: DocumentTypeDefinition[]
): DocumentTypeDefinition[] {
  return commercialDefinitions(documentTypes, "sales");
}

export function dtCodeForRegisterRole(opts: {
  side: RegisterSide;
  role: string;
  documentTypes: DocumentTypeDefinition[];
}): { code: string; label: string } {
  const token = (opts.role || "").trim().toLowerCase();
  const fallbackMap = opts.side === "purchase" ? PURCHASE_FALLBACK : SALES_FALLBACK;
  const fallback = fallbackMap[token] ?? { code: token.toUpperCase(), label: token };

  if (!opts.documentTypes.length) return fallback;

  if (token === "invoice") {
    const commercials = commercialDefinitions(opts.documentTypes, opts.side);
    if (commercials.length) {
      const row = commercials[0];
      return {
        code: row.code.toUpperCase(),
        label: (row.title || row.shortTitle || row.code).trim() || row.code,
      };
    }
    const shipped = opts.documentTypes.find(
      (row) => row.enabled && row.code.toUpperCase() === fallback.code
    );
    if (shipped) {
      return {
        code: fallback.code,
        label: (shipped.title || shipped.shortTitle || shipped.code).trim() || shipped.code,
      };
    }
    return fallback;
  }

  for (const row of opts.documentTypes) {
    if (!row.enabled) continue;
    if (registerRoleForDefinition(row, opts.side) === token) {
      return {
        code: row.code.toUpperCase(),
        label: (row.title || row.shortTitle || row.code).trim() || row.code,
      };
    }
  }

  const shipped = opts.documentTypes.find(
    (row) => row.enabled && row.code.toUpperCase() === fallback.code
  );
  if (shipped) {
    return {
      code: fallback.code,
      label: (shipped.title || shipped.shortTitle || shipped.code).trim() || shipped.code,
    };
  }
  return fallback;
}
