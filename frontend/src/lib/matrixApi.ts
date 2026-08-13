import { api } from "@/api/client";
import type { MatrixRow } from "@/api/types";
import { MATRIX_STAGES, type MatrixCell, type MatrixStage } from "@/lib/matrix";
import { sortInvoicesNewestFirst } from "@/lib/invoices";

export const MATRIX_PAGE_SIZE = 10;

/** Newest ingested matrix rows first (by invoice created_at / id). */
export function sortMatrixRowsNewestFirst(rows: MatrixRow[]): MatrixRow[] {
  const order = new Map(
    sortInvoicesNewestFirst(rows.map((r) => r.invoice)).map((inv, i) => [inv.id, i])
  );
  return [...rows].sort((a, b) => (order.get(a.invoice.id) ?? 0) - (order.get(b.invoice.id) ?? 0));
}

export type MatrixSummary = {
  documentCount: number;
  flagged: number;
  duplicates: number;
  awaiting: number;
  paidThisMonth: number;
};

export type MatrixPageResult = {
  rows: MatrixRow[];
  page: number;
  total: number;
  pages: number;
  summary: MatrixSummary;
};

type MatrixFetchKey = string;
const matrixFetchInflight = new Map<MatrixFetchKey, Promise<MatrixPageResult>>();

function matrixFetchKey(page: number, fresh: boolean, params: Record<string, string>): MatrixFetchKey {
  return `${page}:${fresh ? "fresh" : "cache"}:${JSON.stringify(params)}`;
}

function summaryFromMeta(meta: {
  total?: number;
  matrix_document_count?: number | null;
  matrix_flagged?: number | null;
  matrix_duplicates?: number | null;
  matrix_awaiting?: number | null;
  matrix_paid_this_month?: number | null;
}): MatrixSummary {
  return {
    documentCount: meta.matrix_document_count ?? meta.total ?? 0,
    flagged: meta.matrix_flagged ?? 0,
    duplicates: meta.matrix_duplicates ?? 0,
    awaiting: meta.matrix_awaiting ?? 0,
    paidThisMonth: meta.matrix_paid_this_month ?? 0,
  };
}

/** Fetch one server page of matrix rows plus KPI summary metadata. */
export async function fetchMatrixPage(
  page: number,
  params: Record<string, string> = {},
  fresh = false
): Promise<MatrixPageResult> {
  const key = matrixFetchKey(page, fresh, params);
  const existing = matrixFetchInflight.get(key);
  if (existing && !fresh) return existing;

  const promise = (async () => {
    const res = await api.getMatrixWithMeta(
      {
        page: String(page),
        page_size: String(MATRIX_PAGE_SIZE),
        ...params,
      },
      { fresh }
    );
    return {
      rows: res.data,
      page: res.meta?.page ?? page,
      total: res.meta?.total ?? res.data.length,
      pages: Math.max(1, res.meta?.pages ?? 1),
      summary: summaryFromMeta(res.meta ?? {}),
    };
  })();

  matrixFetchInflight.set(key, promise);
  try {
    return await promise;
  } finally {
    matrixFetchInflight.delete(key);
  }
}

export function stagesToCells(
  stages: MatrixRow["stages"]
): Record<MatrixStage, MatrixCell> {
  const out = {} as Record<MatrixStage, MatrixCell>;
  for (const stage of MATRIX_STAGES) {
    const cell = stages.find((s) => s.stage === stage);
    out[stage as MatrixStage] = {
      state: cell?.state ?? "pending",
      ts: cell?.when ?? "—",
      detail: cell?.detail ?? "—",
    };
  }
  return out;
}
