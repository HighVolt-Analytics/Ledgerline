import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { VendorPayoutMethodCreate, VendorPayoutMethodUpdate } from "@/api/types";
import { queryKeys } from "@/lib/queryClient";

export function useVendorPayoutMethods(vendorId: number | null, enabled = true) {
  return useQuery({
    queryKey: queryKeys.vendorPayoutMethods(vendorId ?? 0),
    queryFn: () => api.listVendorPayoutMethods(vendorId as number),
    enabled: enabled && vendorId != null,
  });
}

export function useVendorPayoutMethodMutations(vendorId: number | null) {
  const queryClient = useQueryClient();

  const invalidate = async () => {
    if (vendorId == null) return;
    await queryClient.invalidateQueries({
      queryKey: queryKeys.vendorPayoutMethods(vendorId),
    });
    await queryClient.invalidateQueries({ queryKey: queryKeys.payments() });
  };

  const createMethod = useMutation({
    mutationFn: (body: VendorPayoutMethodCreate) =>
      api.createVendorPayoutMethod(vendorId as number, body),
    onSuccess: invalidate,
  });

  const updateMethod = useMutation({
    mutationFn: ({
      methodId,
      body,
    }: {
      methodId: number;
      body: VendorPayoutMethodUpdate;
    }) => api.updateVendorPayoutMethod(vendorId as number, methodId, body),
    onSuccess: invalidate,
  });

  const deleteMethod = useMutation({
    mutationFn: (methodId: number) =>
      api.deleteVendorPayoutMethod(vendorId as number, methodId),
    onSuccess: invalidate,
  });

  return { createMethod, updateMethod, deleteMethod };
}
