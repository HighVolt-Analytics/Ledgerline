import type { TaxRatesPayload } from "@/api/types";
import type { IntegrationBrandId } from "@/components/integrations/types";

/**
 * Bill-processing tax adapters. Add a new entry when a platform like QBO
 * owns Settings → Tax rates. The panel switches UI from this registry.
 */
export const BILL_PROCESSING_TAX_ADAPTERS = {
  xero: {
    id: "xero",
    name: "Xero",
    brandId: "xero" as IntegrationBrandId,
    supportsSync: true,
    description:
      "These rates match your connected Xero organisation. New and edited custom rates are written to Xero. Default Xero rates cannot be edited or deleted.",
    emptyRates: "No tax rates synced yet. Use the sync arrow to pull rates from Xero.",
    syncLabel: "Sync tax rates from Xero",
    syncingLabel: "Syncing tax rates from Xero…",
    lockedRateMessage: "This is a default Xero tax rate and cannot be changed.",
  },
} as const;

export type BillProcessingTaxAdapterId = keyof typeof BILL_PROCESSING_TAX_ADAPTERS;

export type ResolvedBillProcessingTaxSource =
  | { kind: "none" }
  | { kind: "adapter"; adapterId: BillProcessingTaxAdapterId }
  | { kind: "unsupported"; providerId: string; providerName: string };

export function resolveBillProcessingTaxSource(
  payload: Pick<TaxRatesPayload, "source" | "provider" | "xero_connected"> | undefined
): ResolvedBillProcessingTaxSource {
  const providerId = (payload?.provider?.id || payload?.source || "").trim().toLowerCase();
  const connected =
    payload?.provider?.connected === true ||
    payload?.xero_connected === true ||
    (providerId !== "" && providerId !== "none");

  if (!connected) {
    return { kind: "none" };
  }

  if (providerId === "xero" || payload?.xero_connected) {
    return { kind: "adapter", adapterId: "xero" };
  }

  if (providerId in BILL_PROCESSING_TAX_ADAPTERS) {
    return { kind: "adapter", adapterId: providerId as BillProcessingTaxAdapterId };
  }

  if (providerId && providerId !== "none") {
    return {
      kind: "unsupported",
      providerId,
      providerName: payload?.provider?.name?.trim() || providerId,
    };
  }

  return { kind: "none" };
}

export function billProcessingTaxAdapter(id: BillProcessingTaxAdapterId) {
  return BILL_PROCESSING_TAX_ADAPTERS[id];
}

export function billProcessingBrandId(providerId: string): IntegrationBrandId | undefined {
  const id = providerId.trim().toLowerCase();
  if (id === "xero") return "xero";
  if (id === "qbo" || id === "quickbooks_online") return "qbo";
  if (id === "myob") return "myob";
  return undefined;
}
