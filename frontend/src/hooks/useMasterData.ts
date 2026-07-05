import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, type EmployeeImportMode, type EmployeeImportResult } from "@/api/client";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";
import {
  employeeMasterFromApi,
  employeeMasterToCreateBody,
  employeeMasterToUpdateBody,
  customerMasterFromApi,
  customerMasterToCreateBody,
  customerMasterToUpdateBody,
  mapPendingVendor,
  vendorMasterFromApi,
  vendorMasterToCreateBody,
  vendorMasterToUpdateBody,
} from "@/lib/masterDataApi";
import type { EmployeeMaster, VendorMaster, CustomerMaster } from "@/lib/v4RuleBookTypes";

export function useCustomerMasters(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.customerMasters(),
    queryFn: async () => {
      const rows = await api.listCustomerMasters();
      return rows.map((row) => customerMasterFromApi(row as Record<string, unknown>));
    },
    enabled,
  });
}

export function useVendorMasters(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.vendorMasters(),
    queryFn: async () => {
      const rows = await api.listVendorMasters();
      return rows.map((row) => vendorMasterFromApi(row as Record<string, unknown>));
    },
    enabled,
  });
}

export function useEmployeeMasters(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.employeeMasters(),
    queryFn: async () => {
      const rows = await api.listEmployeeMasters();
      return rows.map((row) => employeeMasterFromApi(row as Record<string, unknown>));
    },
    enabled,
  });
}

export function usePendingVendors(enabled = true) {
  return useTenantQuery({
    queryKey: queryKeys.pendingVendors(),
    queryFn: async () => {
      const rows = await api.listPendingVendors({ fresh: true });
      return rows.map((row) => mapPendingVendor(row as Record<string, unknown>));
    },
    enabled,
    staleTime: 0,
    refetchOnMount: "always",
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

function patchCustomerInCache(
  queryClient: ReturnType<typeof useQueryClient>,
  updated: CustomerMaster
) {
  queryClient.setQueryData<CustomerMaster[]>(queryKeys.customerMasters(), (rows) =>
    rows?.map((row) => (row.id === updated.id ? updated : row)) ?? [updated]
  );
}

function appendCustomerInCache(queryClient: ReturnType<typeof useQueryClient>, created: CustomerMaster) {
  queryClient.setQueryData<CustomerMaster[]>(queryKeys.customerMasters(), (rows) =>
    rows ? [...rows, created] : [created]
  );
}

function removeCustomerFromCache(queryClient: ReturnType<typeof useQueryClient>, id: string) {
  queryClient.setQueryData<CustomerMaster[]>(queryKeys.customerMasters(), (rows) =>
    rows?.filter((row) => row.id !== id)
  );
}

export function useCreateCustomerMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: Partial<CustomerMaster>) => {
      const raw = await api.createCustomerMaster(customerMasterToCreateBody(body));
      return customerMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: (created) => {
      appendCustomerInCache(queryClient, created);
    },
  });
}

export function useUpdateCustomerMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }: { id: string; patch: Partial<CustomerMaster> }) => {
      const raw = await api.updateCustomerMaster(id, customerMasterToUpdateBody(patch));
      return customerMasterFromApi(raw as Record<string, unknown>);
    },
    onSuccess: (updated) => {
      patchCustomerInCache(queryClient, updated);
    },
  });
}

export function useDeleteCustomerMaster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteCustomerMaster(id),
    onSuccess: (_data, id) => {
      removeCustomerFromCache(queryClient, id);
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
