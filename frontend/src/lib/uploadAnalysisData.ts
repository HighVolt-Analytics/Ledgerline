import type { UploadApprovalStatusKey } from "@/lib/uploadApprovalFilter";

export type CurrencyTotals = Record<string, number>;

/** Approval board column — matches Upload / Approvals kanban. */
export type ApprovalBoardWipRow = {
  key: UploadApprovalStatusKey;
  column: string;
  items: number;
  valueByCurrency: CurrencyTotals;
  avgWaitDays: number;
  flagged: number;
};

export type ProcessingFunnelRow = {
  stage: string;
  count: number;
  delta: number | null;
  pct: number;
};

export type ExceptionMixRow = {
  type: string;
  items: number;
  atRiskByCurrency: CurrencyTotals;
  severity: "High" | "Medium" | "Low";
  highlight?: boolean;
};

export type UploadAnalysisSummary = {
  documentCount: number;
  flagged: number;
  duplicates: number;
  awaiting: number;
  paidThisMonth: number;
  truncated: boolean;
  analyzedCount: number;
};

export type UploadAnalysisDataset = {
  scopeLabel: string;
  periodLabel: string;
  approvalBoard: ApprovalBoardWipRow[];
  processingFunnel: ProcessingFunnelRow[];
  exceptionMix: ExceptionMixRow[];
  summary: UploadAnalysisSummary;
};

export function mergeCurrencyTotals(...maps: Array<CurrencyTotals | undefined>): CurrencyTotals {
  const out: CurrencyTotals = {};
  for (const map of maps) {
    if (!map) continue;
    for (const [code, amount] of Object.entries(map)) {
      if (!Number.isFinite(amount) || amount === 0) continue;
      out[code] = (out[code] ?? 0) + amount;
    }
  }
  return out;
}
