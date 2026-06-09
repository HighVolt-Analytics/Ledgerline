import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { AlertTriangle, CheckCircle2, X } from "lucide-react";
import type { ReconciliationDayDetail } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { invId, money } from "@/lib/format";
import { cn } from "@/lib/cn";

type ReconciliationDetailDrawerProps = {
  detail: ReconciliationDayDetail | null;
  open: boolean;
  onClose: () => void;
  currency?: string;
};

export function ReconciliationDetailDrawer({
  detail,
  open,
  onClose,
  currency = "AUD",
}: ReconciliationDetailDrawerProps) {
  const [mounted, setMounted] = useState(false);
  const [sheetState, setSheetState] = useState<"open" | "closed">("closed");

  useEffect(() => {
    if (open) {
      setMounted(true);
      setSheetState("closed");
      const frame = requestAnimationFrame(() => {
        requestAnimationFrame(() => setSheetState("open"));
      });
      return () => cancelAnimationFrame(frame);
    }
    setSheetState("closed");
    const timer = window.setTimeout(() => setMounted(false), 300);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!mounted) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [mounted, onClose]);

  if (!mounted || !detail) return null;

  const fmt = (v: string) => money(v, currency);

  return createPortal(
    <div className="pointer-events-none" data-testid="drawer-reconciliation-detail">
      <button
        type="button"
        data-state={sheetState}
        className="invoice-drawer-backdrop pointer-events-auto"
        aria-label="Close"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        data-state={sheetState}
        className="invoice-drawer-panel pointer-events-auto flex h-full flex-col gap-0 border-l border-border bg-background p-0 shadow-lg max-w-lg"
      >
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border shrink-0">
          <div>
            <h2 className="text-base font-semibold tnum">{detail.date}</h2>
            <p className="text-xs text-muted-foreground mt-0.5">Daily reconciliation drill-down</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-sm opacity-70 hover:opacity-100"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          <div
            className={cn(
              "rounded-md border p-3 flex items-start gap-2 text-sm",
              detail.is_balanced
                ? "border-[hsl(var(--chart-1)/0.35)] bg-[hsl(var(--chart-1)/0.06)]"
                : "border-destructive/40 bg-destructive/5"
            )}
          >
            {detail.is_balanced ? (
              <CheckCircle2 className="h-4 w-4 text-[hsl(var(--chart-1))] shrink-0 mt-0.5" />
            ) : (
              <AlertTriangle className="h-4 w-4 text-destructive shrink-0 mt-0.5" />
            )}
            <div>
              <p className="font-medium">
                {detail.is_balanced ? "Closed-loop balanced" : "Reconciliation mismatch"}
              </p>
              {!detail.is_balanced && detail.halt_reason && (
                <p className="text-xs text-muted-foreground mt-1">{detail.halt_reason}</p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm">
            <Metric label="Σ Invoice totals" value={fmt(detail.invoices_total)} />
            <Metric label="Σ Debits" value={fmt(detail.total_debits)} />
            <Metric label="Σ Credits" value={fmt(detail.total_credits)} />
            <Metric label="Δ Dr − Cr" value={fmt(detail.delta_dr_cr)} warn={detail.delta_dr_cr !== "0.00"} />
            <Metric label="Δ vs invoices" value={fmt(detail.delta_vs_invoices)} />
            <div className="flex gap-2 items-end">
              <Badge variant="outline" className={detail.rc1_passed ? "text-[hsl(var(--chart-1))]" : "text-destructive"}>
                RC1 {detail.rc1_passed ? "Pass" : "Fail"}
              </Badge>
              <Badge variant="outline" className={detail.rc2_passed ? "text-[hsl(var(--chart-1))]" : "text-destructive"}>
                RC2 {detail.rc2_passed ? "Pass" : "Fail"}
              </Badge>
            </div>
          </div>

          <section>
            <h3 className="text-sm font-semibold mb-2">Contributing invoices</h3>
            {detail.invoices.length === 0 ? (
              <p className="text-sm text-muted-foreground">No processed invoices on this date.</p>
            ) : (
              <ul className="space-y-2">
                {detail.invoices.map((inv) => (
                  <li
                    key={inv.id}
                    className="flex items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm"
                  >
                    <div className="min-w-0">
                      <span className="font-medium tnum">{invId(inv.id)}</span>
                      <span className="text-muted-foreground mx-1">·</span>
                      <span className="truncate">{inv.vendor ?? "—"}</span>
                    </div>
                    <span className="tnum shrink-0">{fmt(inv.total ?? "0")}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h3 className="text-sm font-semibold mb-2">Journal lines</h3>
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-left text-muted-foreground bg-muted/50 border-b border-border">
                    <th className="px-2 py-2 font-medium">Account</th>
                    <th className="px-2 py-2 font-medium text-right">Debit</th>
                    <th className="px-2 py-2 font-medium text-right">Credit</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.journal_lines.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-2 py-4 text-center text-muted-foreground">
                        Journal detail will load from the API.
                      </td>
                    </tr>
                  ) : (
                    detail.journal_lines.map((line) => (
                      <tr key={line.id} className="border-b border-border/60 last:border-0">
                        <td className="px-2 py-2">
                          <div className="tnum">{line.account_code}</div>
                          <div className="text-muted-foreground truncate max-w-[180px]">
                            {line.account_name}
                          </div>
                        </td>
                        <td className="px-2 py-2 text-right tnum">
                          {line.debit !== "0.00" ? fmt(line.debit) : "—"}
                        </td>
                        <td className="px-2 py-2 text-right tnum">
                          {line.credit !== "0.00" ? fmt(line.credit) : "—"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <div className="px-5 py-3 border-t border-border shrink-0">
          <Button variant="outline" size="sm" className="w-full" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}

function Metric({
  label,
  value,
  warn,
}: {
  label: string;
  value: string;
  warn?: boolean;
}) {
  return (
    <div className="rounded-md border border-border p-2.5">
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={cn("text-sm font-semibold tnum mt-0.5", warn && "text-destructive")}>{value}</p>
    </div>
  );
}
