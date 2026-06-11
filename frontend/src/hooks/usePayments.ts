import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";

export function usePayments(enabled = true) {
  return useQuery({
    queryKey: queryKeys.payments,
    queryFn: () => api.listPayments(),
    enabled,
  });
}

export function usePaymentMutations() {
  const queryClient = useQueryClient();

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.payments });
    queryClient.invalidateQueries({ queryKey: queryKeys.navBadges });
  };

  return {
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
