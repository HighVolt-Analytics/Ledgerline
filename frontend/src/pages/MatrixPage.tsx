import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, Ban, Check, Clock, RefreshCw } from "lucide-react";
import type { Invoice, MatrixRow } from "@/api/types";
import { api } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { KpiCard } from "@/components/KpiCard";
import { MatrixFlagBadge } from "@/components/matrix/MatrixFlagBadge";
import { MatrixFlagDrawer } from "@/components/matrix/MatrixFlagDrawer";
import { MatrixPaymentBadge } from "@/components/matrix/MatrixPaymentBadge";
import { MatrixStageCell } from "@/components/matrix/MatrixStageCell";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { invId, money } from "@/lib/format";
import { MATRIX_STAGES, type MatrixStage } from "@/lib/matrix";
import { fetchAllMatrixRows, stagesToCells } from "@/lib/matrixApi";
import type { MatrixFlagType, MatrixPaymentStatus } from "@/lib/v4MatrixMockData";
import { cn } from "@/lib/cn";
import { useVisibilityPolling } from "@/hooks/useVisibilityPolling";

const MATRIX_POLL_MS = 15_000;

const QUEUE_STATUSES = new Set(["exception", "duplicate_skipped", "rejected"]);

type MatrixFilter = "all" | "anomalies" | "awaiting" | "paid";

const FILTER_PILLS: { key: MatrixFilter; label: string }[] = [
  { key: "all", label: "Show all" },
  { key: "anomalies", label: "Anomalies only" },
  { key: "awaiting", label: "Awaiting payment" },
  { key: "paid", label: "Paid this month" },
];

type MatrixTableRow = {
  inv: Invoice;
  cells: ReturnType<typeof stagesToCells>;
  flag: MatrixFlagType;
  payment: MatrixPaymentStatus;
  reason?: string;
  conflictWith?: string;
  conflictDetail?: import("@/lib/v4MatrixMockData").MatrixConflictRow[];
};

function toFlagType(value: string): MatrixFlagType {
  if (value === "Anomaly Detected") return "Anomaly Detected";
  if (value === "Duplicate Suspected") return "Duplicate Suspected";
  if (value === "Quarantined") return "Quarantined";
  return "Clean";
}

function toPaymentStatus(value: string): MatrixPaymentStatus {
  const allowed: MatrixPaymentStatus[] = [
    "Paid",
    "Awaiting Payment",
    "Payment Approved",
    "On Hold",
    "Failed",
    "—",
  ];
  return allowed.includes(value as MatrixPaymentStatus) ? (value as MatrixPaymentStatus) : "—";
}

function rowFromApi(row: MatrixRow): MatrixTableRow {
  const flag = toFlagType(row.flag);
  return {
    inv: row.invoice,
    cells: stagesToCells(row.stages),
    flag,
    payment: toPaymentStatus(row.payment_status),
    reason: row.flag_reason ?? undefined,
    conflictWith: row.conflict_with ?? undefined,
    conflictDetail: row.conflict_detail?.map((line) => ({
      field: line.field,
      thisDoc: line.this_doc,
      otherDoc: line.other_doc,
    })),
  };
}

export function MatrixPage() {
  const [matrixData, setMatrixData] = useState<MatrixRow[]>([]);
  const [filter, setFilter] = useState<MatrixFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [flagDrawerId, setFlagDrawerId] = useState<number | null>(null);
  const [resolveBusy, setResolveBusy] = useState(false);

  const load = useCallback(async (options?: { silent?: boolean; fresh?: boolean }) => {
    if (!options?.silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const fresh = options?.fresh ?? !options?.silent;
      const data = await fetchAllMatrixRows(fresh);
      setMatrixData(data);
    } catch (e) {
      if (!options?.silent) {
        setError(e instanceof Error ? e.message : "Failed to load document matrix");
        setMatrixData([]);
      }
    } finally {
      if (!options?.silent) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useVisibilityPolling(() => {
    void load({ silent: true, fresh: true });
  }, MATRIX_POLL_MS);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 3000);
    return () => clearTimeout(t);
  }, [toast]);

  const matrixRows = useMemo<MatrixTableRow[]>(
    () => matrixData.map(rowFromApi),
    [matrixData]
  );

  const filteredRows = useMemo(
    () =>
      matrixRows.filter((row) => {
        if (filter === "anomalies") {
          return (
            row.flag === "Anomaly Detected" ||
            row.flag === "Duplicate Suspected" ||
            row.flag === "Quarantined"
          );
        }
        if (filter === "awaiting") {
          return row.payment === "Awaiting Payment" || row.payment === "Payment Approved";
        }
        if (filter === "paid") return row.payment === "Paid";
        return true;
      }),
    [matrixRows, filter]
  );

  const kpis = useMemo(
    () => ({
      flagged: matrixRows.filter((r) => r.flag !== "Clean").length,
      duplicates: matrixRows.filter((r) => r.flag === "Duplicate Suspected").length,
      awaiting: matrixRows.filter(
        (r) => r.payment === "Awaiting Payment" || r.payment === "Payment Approved"
      ).length,
      paid: matrixRows.filter((r) => r.payment === "Paid").length,
    }),
    [matrixRows]
  );

  const flagDrawerRow = useMemo(
    () => matrixRows.find((r) => r.inv.id === flagDrawerId) ?? null,
    [matrixRows, flagDrawerId]
  );

  async function resolveFlag(inv: Invoice, action: "unique" | "duplicate" | "approval") {
    setResolveBusy(true);
    try {
      if (action === "unique") {
        if (QUEUE_STATUSES.has(inv.status)) {
          await api.approve(inv.id);
          await api.triggerProcess();
          setToast(`${invId(inv.id)} approved for reprocessing`);
        } else {
          setToast(`${invId(inv.id)} marked as reviewed`);
        }
      } else if (action === "duplicate") {
        if (inv.status === "duplicate_skipped" || inv.status === "rejected") {
          await api.deleteApprovalPermanently(inv.id);
          setToast(`${invId(inv.id)} permanently removed`);
        } else {
          await api.reject(inv.id);
          setToast(`${invId(inv.id)} rejected as duplicate`);
        }
      } else {
        await api.requestApproval(inv.id);
        setToast(`${invId(inv.id)} sent to approvals`);
      }
      setFlagDrawerId(null);
      await load({ silent: true, fresh: true });
    } catch (e) {
      setToast(e instanceof Error ? e.message : "Could not update document");
    } finally {
      setResolveBusy(false);
    }
  }

  if (error) {
    return (
      <Card className="p-6 border-destructive/30 bg-destructive/5 text-sm text-destructive">
        {error}. Ensure the API is running on port 8001.
      </Card>
    );
  }

  return (
    <div>
      {toast && (
        <div className="fixed bottom-4 right-4 z-50 rounded-md border border-border bg-popover px-4 py-2 text-sm shadow-md max-w-sm">
          {toast}
        </div>
      )}

      <PageHeader
        title="Document Matrix"
        subtitle="Pipeline stage status, anomaly detection, and payment readiness. Flagged documents are blocked from progressing until cleared."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => load({ fresh: true })}
            disabled={loading}
          >
            <RefreshCw className={cn("h-4 w-4 mr-1", loading && "animate-spin")} />
            Refresh
          </Button>
        }
      />

      {loading && matrixData.length === 0 ? (
        <Card className="p-8 text-center text-sm text-muted-foreground">Loading matrix…</Card>
      ) : matrixData.length === 0 ? (
        <EmptyState
          title="No documents in the matrix"
          hint="Connect a mailbox and fetch from Inbox, or upload an invoice from Integrations."
          action={
            <Link
              to="/inbox"
              className="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary/90"
            >
              Go to Inbox
            </Link>
          }
        />
      ) : (
        <>
          <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-5">
            <KpiCard label="Documents" value={matrixRows.length} testid="kpi-matrix-docs" />
            <KpiCard
              label="Flagged for review"
              value={kpis.flagged}
              testid="kpi-matrix-flagged"
              delta={
                kpis.flagged > 0
                  ? { dir: "up", text: `${kpis.duplicates} duplicates`, good: false }
                  : undefined
              }
            />
            <KpiCard
              label="Awaiting payment"
              value={kpis.awaiting}
              testid="kpi-matrix-awaiting"
            />
            <KpiCard label="Paid this month" value={kpis.paid} testid="kpi-matrix-paid" />
          </div>

          <div className="flex flex-wrap items-center gap-2 mb-3">
            {FILTER_PILLS.map((pill) => (
              <button
                key={pill.key}
                type="button"
                onClick={() => setFilter(pill.key)}
                data-testid={`matrix-filter-${pill.key}`}
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-medium border transition-colors",
                  filter === pill.key
                    ? "bg-primary text-primary-foreground border-primary"
                    : "border-border text-muted-foreground hover:text-foreground hover-elevate"
                )}
              >
                {pill.label}
              </button>
            ))}
            <span className="ml-auto text-xs text-muted-foreground">
              {filteredRows.length} of {matrixRows.length} documents
            </span>
          </div>

          <Card className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead>
                  <tr className="text-xs text-muted-foreground border-b border-border">
                    <th className="px-4 py-2.5 text-left font-medium sticky left-0 bg-card z-10">
                      Document
                    </th>
                    <th className="px-3 py-2.5 text-left font-medium">Vendor</th>
                    {MATRIX_STAGES.map((stage) => (
                      <th key={stage} className="px-3 py-2.5 text-center font-medium">
                        {stage}
                      </th>
                    ))}
                    <th className="px-3 py-2.5 text-left font-medium border-l border-border">
                      Anomaly / Duplicate
                    </th>
                    <th className="px-3 py-2.5 text-left font-medium">Payment Status</th>
                    <th className="px-4 py-2.5 text-right font-medium">Total</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredRows.map(({ inv, cells, flag, payment }) => {
                    const docId = invId(inv.id);
                    const flagged = flag !== "Clean";
                    return (
                      <tr
                        key={inv.id}
                        className="row-band border-b border-border/60 last:border-0"
                      >
                        <td className="px-4 py-2 sticky left-0 bg-card z-10">
                          <div className="font-medium">{docId}</div>
                          <div className="text-xs text-muted-foreground tnum">
                            {inv.invoice_no ?? `DOC-${inv.id}`}
                          </div>
                        </td>
                        <td className="px-3 py-2 max-w-[150px] truncate text-muted-foreground">
                          {inv.vendor ?? "—"}
                        </td>
                        {MATRIX_STAGES.map((stage) => {
                          const blocked = flagged && (stage === "Approved" || stage === "Published");
                          return (
                            <td key={stage} className="px-3 py-2 text-center">
                              <MatrixStageCell
                                stage={stage as MatrixStage}
                                cell={cells[stage as MatrixStage]}
                                blocked={blocked}
                                flag={flag}
                              />
                            </td>
                          );
                        })}
                        <td className="px-3 py-2 border-l border-border">
                          {flagged ? (
                            <button
                              type="button"
                              onClick={() => setFlagDrawerId(inv.id)}
                              data-testid={`matrix-flag-${docId}`}
                              className="text-left"
                            >
                              <MatrixFlagBadge flag={flag} />
                            </button>
                          ) : (
                            <MatrixFlagBadge flag={flag} />
                          )}
                        </td>
                        <td className="px-3 py-2">
                          <MatrixPaymentBadge status={payment} />
                        </td>
                        <td className="px-4 py-2 text-right tnum font-medium">
                          {money(inv.total, inv.currency)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>

          <p className="text-xs text-muted-foreground mt-3 flex items-center gap-4 flex-wrap">
            <span className="inline-flex items-center gap-1">
              <Check className="h-3.5 w-3.5 text-[hsl(var(--chart-1))]" />
              Complete
            </span>
            <span className="inline-flex items-center gap-1">
              <Clock className="h-3.5 w-3.5" />
              Pending
            </span>
            <span className="inline-flex items-center gap-1">
              <Ban className="h-3.5 w-3.5 text-destructive" />
              Failed / blocked
            </span>
            <span className="inline-flex items-center gap-1">
              <AlertTriangle className="h-3.5 w-3.5 text-[hsl(43_74%_49%)]" />
              Anomaly routes through approval before payment
            </span>
          </p>
        </>
      )}

      <MatrixFlagDrawer
        row={
          flagDrawerRow
            ? {
                inv: flagDrawerRow.inv,
                flag: flagDrawerRow.flag,
                reason: flagDrawerRow.reason,
                conflictWith: flagDrawerRow.conflictWith,
                conflictDetail: flagDrawerRow.conflictDetail,
              }
            : null
        }
        open={flagDrawerId !== null}
        onClose={() => setFlagDrawerId(null)}
        busy={resolveBusy}
        onResolve={(_docId, action) => {
          const inv = flagDrawerRow?.inv;
          if (inv) void resolveFlag(inv, action);
        }}
      />
    </div>
  );
}
