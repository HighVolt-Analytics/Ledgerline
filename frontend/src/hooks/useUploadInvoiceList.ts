import { useEffect, useState, useSyncExternalStore } from "react";
import { type QueryClient } from "@tanstack/react-query";
import { api } from "@/api/client";
import type { Invoice } from "@/api/types";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys, tenantQueryKey } from "@/lib/queryClient";
import { uploadListHasActiveProcessing } from "@/lib/uploadColumnState";

const INBOX_POLL_MS = 15_000;
const INBOX_POLL_FAST_MS = 4_000;

export type UploadInvoiceListData = {
  rows: Invoice[];
  total: number;
  pages: number;
};

function subscribeVisibility(onChange: () => void): () => void {
  document.addEventListener("visibilitychange", onChange);
  return () => document.removeEventListener("visibilitychange", onChange);
}

function getVisibility(): DocumentVisibilityState {
  return document.visibilityState;
}

function serverVisibility(): DocumentVisibilityState {
  return "visible";
}

export function invalidateUploadInvoiceList(queryClient: QueryClient): Promise<void> {
  return queryClient.invalidateQueries({
    queryKey: tenantQueryKey(["invoices", "upload"]),
  });
}

export function useUploadInvoiceList(options: {
  page: number;
  pageSize: number;
  source: string;
  q: string;
  mailboxId: number | null;
  captureSource: "upload" | "email" | "whatsapp" | "viber";
  enabled?: boolean;
  processingIds?: ReadonlySet<number>;
}) {
  const {
    page,
    pageSize,
    source,
    q,
    mailboxId,
    captureSource,
    enabled = true,
    processingIds,
  } = options;
  const visibility = useSyncExternalStore(
    subscribeVisibility,
    getVisibility,
    serverVisibility
  );
  const [pollInterval, setPollInterval] = useState(INBOX_POLL_MS);

  const query = useTenantQuery<UploadInvoiceListData>({
    queryKey: queryKeys.uploadDocuments(page, pageSize, source, q, mailboxId, captureSource),
    enabled,
    // Keep prior rows while search/page changes, but not when the channel tab changes.
    placeholderData: (previousData, previousQuery) => {
      if (!previousData || !previousQuery) return undefined;
      const prevKey = previousQuery.queryKey;
      const prevCapture = prevKey[prevKey.length - 1];
      if (prevCapture !== captureSource) return undefined;
      return previousData;
    },
    queryFn: async () => {
      const params: Record<string, string> = {
        page: String(page),
        page_size: String(pageSize),
        capture_source: captureSource,
      };
      if (mailboxId != null) {
        params.connected_mailbox_id = String(mailboxId);
      }
      if (q) {
        params.q = q;
      }
      const res = await api.listInvoicesWithMeta(params);
      return {
        rows: res.data,
        total: res.meta?.total ?? res.data.length,
        pages: Math.max(1, res.meta?.pages ?? 1),
      };
    },
    refetchIntervalInBackground: false,
    refetchInterval: visibility === "visible" ? pollInterval : false,
  });

  useEffect(() => {
    const rows = query.data?.rows ?? [];
    const busy = uploadListHasActiveProcessing(rows, processingIds);
    setPollInterval(busy ? INBOX_POLL_FAST_MS : INBOX_POLL_MS);
  }, [query.data?.rows, processingIds]);

  return query;
}
