import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type EmployeeImportMode, type EmployeeImportResult } from "@/api/client";
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
    queryKey: queryKeys.vendorMasters(),
    queryFn: async () => {
      const rows = await api.listVendorMasters();
      return rows.map((row) => vendorMasterFromApi(row as Record<string, unknown>));
    },
    enabled,
  });
}

export function useEmployeeMasters(enabled = true) {
  return useQuery({
    queryKey: queryKeys.employeeMasters(),
    queryFn: async () => {
      const rows = await api.listEmployeeMasters();
      return rows.map((row) => employeeMasterFromApi(row as Record<string, unknown>));
    },
    enabled,
  });
}

export function usePendingVendors(enabled = true) {
  return useQuery({
    queryKey: queryKeys.pendingVendors(),
    queryFn: async () => {
      const rows = await api.listPendingVendors();
      return rows.map((row) => mapPendingVendor(row as Record<string, unknown>));
    },
    enabled,
  });
}

function patchVendorInCache(
  queryClient: ReturnType<typeof useQueryClient>,
  updated: VendorMaster
) {
  queryClient.setQueryData<VendorMaster[]>(queryKeys.vendorMasters(), (rows) =>
    rows?.map((row) => (row.id === updated.id ? updated : row)) ?? [updated]
  );
}

function appendVendorInCache(queryClient: ReturnType<typeof useQueryClient>, created: VendorMaster) {
  queryClient.setQueryData<VendorMaster[]>(queryKeys.vendorMasters(), (rows) =>
    rows ? [...rows, created] : [created]
  );
}

function removeVendorFromCache(queryClient: ReturnType<typeof useQueryClient>, id: string) {
  queryClient.setQueryData<VendorMaster[]>(queryKeys.vendorMasters(), (rows) =>
    rows?.filter((row) => row.id !== id)
  );
}

function invalidatePendingVendors(queryClient: ReturnType<typeof useQueryClient>) {
  void queryClient.invalidateQueries({ queryKey: queryKeys.pendingVendors() });
}

export function useCreateVendorMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<VendorMaster>) => {
      const raw = await api.createVendorMaster(vendorMasterToCreateBody(body));
      return vendorMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: (created) => {
      appendVendorInCache(queryClient, created);
      invalidatePendingVendors(queryClient);
    },
  });
}

export function useUpdateVendorMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: Partial<VendorMaster> }) => {
      const raw = await api.updateVendorMaster(id, vendorMasterToUpdateBody(patch));
      return vendorMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: (updated) => {
      patchVendorInCache(queryClient, updated);
    },
  });
}

export function useDeleteVendorMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteVendorMaster(id),
    onSuccess: (_data, id) => {
      removeVendorFromCache(queryClient, id);
    },
  });
}

export function useCreateEmployeeMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<EmployeeMaster>) => {
      const raw = await api.createEmployeeMaster(employeeMasterToCreateBody(body));
      return employeeMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: (created) => {
      queryClient.setQueryData<EmployeeMaster[]>(queryKeys.employeeMasters(), (rows) =>
        rows ? [...rows, created] : [created]
      );
    },
  });
}

export function useUpdateEmployeeMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: Partial<EmployeeMaster> }) => {
      const raw = await api.updateEmployeeMaster(id, employeeMasterToUpdateBody(patch));
      return employeeMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: (updated) => {
      queryClient.setQueryData<EmployeeMaster[]>(queryKeys.employeeMasters(), (rows) =>
        rows?.map((row) => (row.id === updated.id ? updated : row))
      );
    },
  });
}

export function useDeleteEmployeeMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteEmployeeMaster(id),
    onSuccess: (_data, id) => {
      queryClient.setQueryData<EmployeeMaster[]>(queryKeys.employeeMasters(), (rows) =>
        rows?.filter((row) => row.id !== id)
      );
    },
  });
}

export function useImportEmployeeMasters() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({
      mode,
      file,
      dryRun,
    }: {
      mode: EmployeeImportMode;
      file: File;
      dryRun: boolean;
    }) => api.importEmployeeMasters(mode, file, dryRun),
    onSuccess: (result: EmployeeImportResult) => {
      if (!result.dry_run) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.employeeMasters() });
      }
    },
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
    onSuccess: (vendor) => {
      appendVendorInCache(queryClient, vendor);
      invalidatePendingVendors(queryClient);
    },
  });
}

export function useDismissPendingVendor() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (pendingId: number) => api.dismissPendingVendor(pendingId),
    onSuccess: () => invalidatePendingVendors(queryClient),
  });
}
