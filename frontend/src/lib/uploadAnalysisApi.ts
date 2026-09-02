import { api } from "@/api/client";
import type {
  ApprovalBoardWipRow,
  CurrencyTotals,
  ExceptionMixRow,
  ProcessingFunnelRow,
  UploadAnalysisDataset,
} from "@/lib/uploadAnalysisData";
import {
  AREA_ANALYSIS_LABEL,
  CHANNEL_FUNNEL_LABEL,
  uploadChannelLabel,
  type UploadAnalysisScope,
} from "@/lib/uploadAnalysisScope";
import {
  routeTargetsForDocumentAreas,
  serializeUploadApprovalFilter,
  UPLOAD_APPROVAL_STATUS_FILTERS,
  type UploadApprovalStatusKey,
} from "@/lib/uploadApprovalFilter";

export type MatrixAnalysisApiResponse = {
  approval_board: Array<{
    key: UploadApprovalStatusKey;
    column: string;
    items: number;
    value_by_currency: CurrencyTotals;
    avg_wait_days: number;
    flagged: number;
  }>;
  processing_funnel: Array<{
    stage: string;
    count: number;
    delta: number | null;
    pct: number;
  }>;
  exception_mix: Array<{
    type: string;
    items: number;
    at_risk_by_currency: CurrencyTotals;
    severity: "High" | "Medium" | "Low";
    highlight?: boolean;
  }>;
  summary: {
    document_count: number;
    flagged: number;
    duplicates: number;
    awaiting: number;
    paid_this_month: number;
    truncated: boolean;
    analyzed_count: number;
  };
};

function resolveScopeLabel(scope: UploadAnalysisScope): string {
  const channel = uploadChannelLabel(scope.channel);
  if (scope.documentAreas.length === 1) {
    return `${channel} · ${AREA_ANALYSIS_LABEL[scope.documentAreas[0]!]}`;
  }
  if (scope.documentAreas.length > 1) {
    return `${channel} · ${scope.documentAreas.length} areas`;
  }
  return channel;
}

function resolvePeriodLabel(scope: UploadAnalysisScope): string {
  const areaLabel =
    scope.documentAreas.length === 0
      ? null
      : scope.documentAreas.length === 1
        ? AREA_ANALYSIS_LABEL[scope.documentAreas[0]!]
        : `${scope.documentAreas.length} areas`;

  return areaLabel
    ? `${CHANNEL_FUNNEL_LABEL[scope.channel]} · ${areaLabel}`
    : CHANNEL_FUNNEL_LABEL[scope.channel];
}

export function uploadAnalysisQueryParams(scope: UploadAnalysisScope): Record<string, string> {
  const params: Record<string, string> = {};
  if (scope.channel !== "all" && scope.channel !== "bank-feeds") {
    params.capture_source = scope.channel;
  }
  const routeTarget = routeTargetsForDocumentAreas(scope.documentAreas);
  if (routeTarget) params.route_target = routeTarget;
  if (scope.searchQuery.trim()) params.q = scope.searchQuery.trim();
  const approval = serializeUploadApprovalFilter(scope.approvalFilter);
  if (approval) params.approval_board_column = approval;
  return params;
}

function mapBoard(rows: MatrixAnalysisApiResponse["approval_board"]): ApprovalBoardWipRow[] {
  const order = UPLOAD_APPROVAL_STATUS_FILTERS.map((item) => item.key);
  const byKey = new Map(rows.map((row) => [row.key, row]));
  return order.map((key) => {
    const row = byKey.get(key);
    return {
      key,
      column: row?.column ?? UPLOAD_APPROVAL_STATUS_FILTERS.find((item) => item.key === key)?.label ?? key,
      items: row?.items ?? 0,
      valueByCurrency: row?.value_by_currency ?? {},
      avgWaitDays: row?.avg_wait_days ?? 0,
      flagged: row?.flagged ?? 0,
    };
  });
}

function mapFunnel(rows: MatrixAnalysisApiResponse["processing_funnel"]): ProcessingFunnelRow[] {
  return rows.map((row) => ({
    stage: row.stage,
    count: row.count,
    delta: row.delta,
    pct: row.pct,
  }));
}

function mapIssues(rows: MatrixAnalysisApiResponse["exception_mix"]): ExceptionMixRow[] {
  return rows.map((row) => ({
    type: row.type,
    items: row.items,
    atRiskByCurrency: row.at_risk_by_currency ?? {},
    severity: row.severity,
    highlight: row.highlight,
  }));
}

export function mapMatrixAnalysisToDataset(
  scope: UploadAnalysisScope,
  payload: MatrixAnalysisApiResponse
): UploadAnalysisDataset {
  return {
    scopeLabel: resolveScopeLabel(scope),
    periodLabel: resolvePeriodLabel(scope),
    approvalBoard: mapBoard(payload.approval_board),
    processingFunnel: mapFunnel(payload.processing_funnel),
    exceptionMix: mapIssues(payload.exception_mix),
    summary: {
      documentCount: payload.summary.document_count,
      flagged: payload.summary.flagged,
      duplicates: payload.summary.duplicates,
      awaiting: payload.summary.awaiting,
      paidThisMonth: payload.summary.paid_this_month,
      truncated: payload.summary.truncated,
      analyzedCount: payload.summary.analyzed_count,
    },
  };
}

export async function fetchUploadAnalysis(
  scope: UploadAnalysisScope,
  fresh = true
): Promise<UploadAnalysisDataset | null> {
  if (scope.channel === "bank-feeds" || scope.view === "setup") return null;
  const params = uploadAnalysisQueryParams(scope);
  const res = await api.getMatrixAnalysis(params, { fresh });
  if (!res.data) return null;
  return mapMatrixAnalysisToDataset(scope, res.data);
}
