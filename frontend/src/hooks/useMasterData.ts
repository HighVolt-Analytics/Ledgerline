import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import { queryKeys } from "@/lib/queryClient";
import {
  employeeMasterFromApi,
  employeeMasterToCreateBody,
  employeeMasterToUpdateBody,
  mapPendingVendor,
  vendorMasterFromApi,
  vendorMasterToCreateBody,
  vendorMasterToUpdateBody,
} from "@/lib/masterDataApi";
import type { EmployeeMaster, VendorMaster } from "@/lib/v4RuleBookTypes";

export function useVendorMasters(enabled = true) {
  return useQuery({
    queryKey: queryKeys.vendorMasters,
    queryFn: async () => {
      const rows = await api.listVendorMasters();
      return rows.map((row) => vendorMasterFromApi(row as Record<string, unknown>));
    },
    enabled,
  });
}

export function useEmployeeMasters(enabled = true) {
  return useQuery({
    queryKey: queryKeys.employeeMasters,
    queryFn: async () => {
      const rows = await api.listEmployeeMasters();
      return rows.map((row) => employeeMasterFromApi(row as Record<string, unknown>));
    },
    enabled,
  });
}

export function usePendingVendors(enabled = true) {
  return useQuery({
    queryKey: queryKeys.pendingVendors,
    queryFn: async () => {
      const rows = await api.listPendingVendors();
      return rows.map((row) => mapPendingVendor(row as Record<string, unknown>));
    },
    enabled,
  });
}

function invalidateMasterQueries(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: queryKeys.vendorMasters });
  queryClient.invalidateQueries({ queryKey: queryKeys.employeeMasters });
  queryClient.invalidateQueries({ queryKey: queryKeys.pendingVendors });
  queryClient.invalidateQueries({ queryKey: queryKeys.ruleBookConfig });
}

export function useCreateVendorMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<VendorMaster>) => {
      const raw = await api.createVendorMaster(vendorMasterToCreateBody(body));
      return vendorMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: () => invalidateMasterQueries(queryClient),
  });
}

export function useUpdateVendorMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: Partial<VendorMaster> }) => {
      const raw = await api.updateVendorMaster(id, vendorMasterToUpdateBody(patch));
      return vendorMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: () => invalidateMasterQueries(queryClient),
  });
}

export function useDeleteVendorMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteVendorMaster(id),
    onSuccess: () => invalidateMasterQueries(queryClient),
  });
}

export function useCreateEmployeeMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<EmployeeMaster>) => {
      const raw = await api.createEmployeeMaster(employeeMasterToCreateBody(body));
      return employeeMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: () => invalidateMasterQueries(queryClient),
  });
}

export function useUpdateEmployeeMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: Partial<EmployeeMaster> }) => {
      const raw = await api.updateEmployeeMaster(id, employeeMasterToUpdateBody(patch));
      return employeeMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: () => invalidateMasterQueries(queryClient),
  });
}

export function useDeleteEmployeeMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteEmployeeMaster(id),
    onSuccess: () => invalidateMasterQueries(queryClient),
  });
}

export function usePromotePendingVendor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      pendingId,
      body,
    }: {
      pendingId: number;
      body: { masterId?: string; name?: string; abn?: string; defaultLedger?: string; status?: string };
    }) => {
      const raw = await api.promotePendingVendor(pendingId, {
        master_id: body.masterId,
        name: body.name,
        abn: body.abn,
        default_ledger: body.defaultLedger,
        status: body.status,
      });
      return vendorMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: () => invalidateMasterQueries(queryClient),
  });
}

export function useDismissPendingVendor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pendingId: number) => api.dismissPendingVendor(pendingId),
    onSuccess: () => invalidateMasterQueries(queryClient),
  });
}
