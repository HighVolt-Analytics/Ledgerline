import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";
import type { PaymentTab } from "@/lib/v4MockData";

export const PAYMENTS_PAGE_SIZE = 50;

export function usePayments(status: PaymentTab, enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.payments(status),
    queryFn: () => api.listPayments(status, { limit: PAYMENTS_PAGE_SIZE }),
    enabled,
  });
}

export function usePaymentWorkspaceKpis(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.paymentsWorkspaceKpis(),
    queryFn: () => api.getPaymentWorkspaceKpis(),
    enabled,
  });
}

export function useAppSettings(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.appSettings(),
    queryFn: () => api.getSettings(),
    enabled,
  });
}

export function useValidatePaymentExecutionReadiness() {
  return useMutation({
    mutationFn: (paymentId: number) => api.validatePaymentExecutionReadiness(paymentId),
  });
}

export function useApprovePayment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (paymentId: number) => api.approvePayment(paymentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.payments() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.paymentsWorkspaceKpis() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
    },
  });
}

export function useCreatePaymentExecutionInstruction() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (paymentId: number) => api.createPaymentExecutionInstruction(paymentId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.payments() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.paymentsWorkspaceKpis() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
    },
  });
}

export function useMarkPaymentPaidManual() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      paymentId,
      body,
    }: {
      paymentId: number;
      body: { reference: string; paid_date: string; proof_reference: string; note?: string };
    }) => api.markPaymentPaidManual(paymentId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.payments() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.paymentsWorkspaceKpis() });
      await queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
    },
  });
}

export function usePaymentMutations() {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.payments() });
    queryClient.invalidateQueries({ queryKey: queryKeys.paymentsWorkspaceKpis() });
    queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
  };

  return {
    approvePayment: async (paymentId: number) => {
      const row = await api.approvePayment(paymentId);
      await invalidate();
      return row;
    },
    updateStatus: async (
      paymentId: number,
      body: {
        status: string;
        scheduled_date?: string;
        payment_intent?: string;
        failure_reason?: string;
      }
    ) => {
      const row = await api.updatePayment(paymentId, body);
      await invalidate();
      return row;
    },
  };
}
