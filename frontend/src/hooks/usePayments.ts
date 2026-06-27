import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function usePayments(enabled = true) {
  return useQuery({
    queryKey: queryKeys.payments(),
    queryFn: () => api.listPayments(),
    enabled,
  });
}

export function useAppSettings(enabled = true) {
  return useQuery({
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
      await queryClient.invalidateQueries({ queryKey: queryKeys.navBadges() });
    },
  });
}

export function usePaymentMutations() {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.payments() });
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
