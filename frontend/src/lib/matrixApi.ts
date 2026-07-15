import { api } from "@/api/client";
import type { MatrixRow } from "@/api/types";
import { MATRIX_STAGES, type MatrixCell, type MatrixStage } from "@/lib/matrix";
import { sortInvoicesNewestFirst } from "@/lib/invoices";

const DEFAULT_PAGE_SIZE = "100";

/** Newest ingested matrix rows first (by invoice created_at / id). */
export function sortMatrixRowsNewestFirst(rows: MatrixRow[]): MatrixRow[] {
  const order = new Map(
    sortInvoicesNewestFirst(rows.map((r) => r.invoice)).map((inv, i) => [inv.id, i])
  );
  return [...rows].sort((a, b) => (order.get(a.invoice.id) ?? 0) - (order.get(b.invoice.id) ?? 0));
}

type MatrixFetchKey = string;
const matrixFetchInflight = new Map<MatrixFetchKey, Promise<MatrixRow[]>>();

function matrixFetchKey(fresh: boolean, params: Record<string, string>): MatrixFetchKey {
  return `${fresh ? "fresh" : "cache"}:${JSON.stringify(params)}`;
}

/** Fetch every matrix page; remaining pages load in parallel after page 1. */
export async function fetchAllMatrixRows(
  fresh = false,
  params: Record<string, string> = {}
): Promise<MatrixRow[]> {
  const key = matrixFetchKey(fresh, params);
  const existing = matrixFetchInflight.get(key);
  if (existing) return existing;

  const promise = (async () => {
    const first = await api.getMatrixWithMeta(
      { page: "1", page_size: DEFAULT_PAGE_SIZE, ...params },
      { fresh }
    );
    const pages = first.meta.pages ?? 1;
    if (pages <= 1) return first.data;

    const rest = await Promise.all(
      Array.from({ length: pages - 1 }, (_, i) =>
        api.getMatrixWithMeta({
          page: String(i + 2),
          page_size: DEFAULT_PAGE_SIZE,
          ...params,
        })
      )
    );
    return [...first.data, ...rest.flatMap((r) => r.data)];
  })();

  matrixFetchInflight.set(key, promise);
  try {
    return await promise;
  } finally {
    matrixFetchInflight.delete(key);
  }
}

function actorFromDetail(detail?: string | null): string {
  return detail?.trim() || "—";
}

export function stagesToCells(stages: MatrixRow["stages"]): Record<MatrixStage, MatrixCell> {
  const cells = {} as Record<MatrixStage, MatrixCell>;
  for (const stage of MATRIX_STAGES) {
    const hit = stages.find((s) => s.stage === stage);
    cells[stage] = {
      state: (hit?.state ?? "pending") as MatrixCell["state"],
      ts: hit?.when ?? "—",
      detail: actorFromDetail(hit?.detail),
    };
  }
  return cells;
}
