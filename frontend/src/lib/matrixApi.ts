import { api } from "@/api/client";
import type { MatrixRow } from "@/api/types";
import { MATRIX_STAGES, type MatrixCell, type MatrixStage } from "@/lib/matrix";

const DEFAULT_PAGE_SIZE = "100";

export async function fetchAllMatrixRows(
  fresh = false,
  params: Record<string, string> = {}
): Promise<MatrixRow[]> {
  const all: MatrixRow[] = [];
  let page = 1;
  let pages = 1;
  do {
    const res = await api.getMatrixWithMeta(
      { page: String(page), page_size: DEFAULT_PAGE_SIZE, ...params },
      { fresh: fresh && page === 1 }
    );
    all.push(...res.data);
    pages = res.meta.pages ?? 1;
    page += 1;
  } while (page <= pages);
  return all;
}

function actorFromDetail(detail?: string | null): string {
  if (!detail) return "—";
  const parts = detail.split(" · ");
  return parts.length > 1 ? parts[parts.length - 1].trim() : detail;
}

export function stagesToCells(stages: MatrixRow["stages"]): Record<MatrixStage, MatrixCell> {
  const cells = {} as Record<MatrixStage, MatrixCell>;
  for (const stage of MATRIX_STAGES) {
    const hit = stages.find((s) => s.stage === stage);
    cells[stage] = {
      state: (hit?.state ?? "pending") as MatrixCell["state"],
      ts: hit?.when ?? "—",
      actor: actorFromDetail(hit?.detail),
    };
  }
  return cells;
}
