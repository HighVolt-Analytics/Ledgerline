import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Invoice } from "@/api/types";
import {
  approveAndProcess,
  canApproveClaim,
  canRejectClaim,
  canRequestInfo,
} from "@/lib/invoiceActions";
import { queryKeys } from "@/lib/queryClient";

export function useExpenseClaimActions(routeTarget: string) {
  const queryClient = useQueryClient();
  const [busyId, setBusyId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.routedInvoices(routeTarget) }),
      queryClient.invalidateQueries({ queryKey: queryKeys.navBadges }),
    ]);
  }, [queryClient, routeTarget]);

  const approve = useCallback(
    async (inv: Invoice) => {
      if (!canApproveClaim(inv.status)) {
        setToast("This claim is not in the approval queue.");
        return false;
      }
      if (!inv.has_stored_file) {
        setToast("Upload a receipt before approving this claim.");
        return false;
      }
      setBusyId(inv.id);
      try {
        setToast("Claim queued for processing…");
        await approveAndProcess(inv.id, refresh);
        setToast("Claim approved — processing complete");
        return true;
      } catch (e) {
        setToast(e instanceof Error ? e.message : "Approve failed");
        return false;
      } finally {
        setBusyId(null);
      }
    },
    [refresh]
  );

  const reject = useCallback(
    async (inv: Invoice) => {
      if (!canRejectClaim(inv.status)) {
        setToast("This claim cannot be rejected.");
        return false;
      }
      setBusyId(inv.id);
      try {
        await api.reject(inv.id);
        await refresh();
        setToast("Claim rejected");
        return true;
      } catch (e) {
        setToast(e instanceof Error ? e.message : "Reject failed");
        return false;
      } finally {
        setBusyId(null);
      }
    },
    [refresh]
  );

  const requestInfo = useCallback(
    async (inv: Invoice) => {
      if (!canRequestInfo(inv.status)) {
        setToast("This claim is already awaiting review.");
        return false;
      }
      setBusyId(inv.id);
      try {
        await api.requestApproval(inv.id);
        await refresh();
        setToast("Claim routed for review");
        return true;
      } catch (e) {
        setToast(e instanceof Error ? e.message : "Request failed");
        return false;
      } finally {
        setBusyId(null);
      }
    },
    [refresh]
  );

  return {
    approve,
    reject,
    requestInfo,
    busyId,
    toast,
    setToast,
    refresh,
    canApproveClaim,
    canRejectClaim,
    canRequestInfo,
  };
}
