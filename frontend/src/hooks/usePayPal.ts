import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type {
  PaypalConnectResponse,
  PaypalPayoutRequest,
} from "@/api/types";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

async function invalidatePaypalQueries(
  queryClient: ReturnType<typeof useQueryClient>
) {
  await queryClient.invalidateQueries({ queryKey: queryKeys.paypalReadiness() });
  await queryClient.invalidateQueries({ queryKey: queryKeys.paypalBalance() });
  await queryClient.invalidateQueries({
    predicate: (query) => query.queryKey.includes("paypalTransactions"),
  });
  await queryClient.invalidateQueries({ queryKey: queryKeys.payments() });
}

export function usePayPalReadiness(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.paypalReadiness(),
    queryFn: () => api.getPaypalReadiness(),
    enabled,
  });
}

export function useConnectPayPal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (): Promise<PaypalConnectResponse> => api.connectPaypal(),
    onSuccess: async () => {
      await invalidatePaypalQueries(queryClient);
    },
  });
}

export function useDisconnectPayPal() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.disconnectPaypal(),
    onSuccess: async () => {
      await invalidatePaypalQueries(queryClient);
    },
  });
}

export function useRefreshPayPalReadiness() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.getPaypalReadiness({ fresh: true }),
    onSuccess: async () => {
      await invalidatePaypalQueries(queryClient);
    },
  });
}

export function usePayPalBalance(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.paypalBalance(),
    queryFn: () => api.getPaypalBalance(),
    enabled,
  });
}

export function usePayPalTransactions(limit = 20, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.paypalTransactions(limit),
    queryFn: () => api.listPaypalTransactions(limit),
    enabled,
  });
}

export function useCreatePayPalPayout() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (body: PaypalPayoutRequest) => api.createPaypalPayout(body),
    onSuccess: async () => {
      await invalidatePaypalQueries(queryClient);
    },
  });
}

export function useRefreshPayPalPayout() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (attemptId: number) => api.refreshPaypalPayout(attemptId),
    onSuccess: async () => {
      await invalidatePaypalQueries(queryClient);
    },
  });
}

/** Resolve first usable PayPal vendor payout method, or null. */
export async function resolvePaypalRecipientMethodId(
  vendorName: string
): Promise<number | null> {
  const vendors = await api.listVendors();
  const needle = vendorName.trim().toLowerCase();
  const vendor = vendors.find((row) => row.vendor_name.trim().toLowerCase() === needle);
  if (!vendor) return null;

  const methods = await api.listVendorPayoutMethods(vendor.id);
  const paypalMethods = methods.filter((method) => {
    const type = (method.method_type || "").toLowerCase();
    const provider = (method.provider || "").toLowerCase();
    return type === "paypal" || provider === "paypal";
  });
  if (!paypalMethods.length) return null;

  const preferred =
    paypalMethods.find((method) => method.is_default && method.status !== "disabled") ??
    paypalMethods.find((method) => method.status === "verified") ??
    paypalMethods.find((method) => method.status !== "disabled") ??
    paypalMethods[0];

  return preferred?.id ?? null;
}
