import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  ShieldCheck,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TableStatusTag, authSyncStatusTone } from "@/components/upload/allDocumentsTablePills";
import type {
  TransactionAuthKind,
  TransactionAuthStep,
  TransactionAuthView,
} from "@/lib/transactionAuth";
import { cn } from "@/lib/cn";
import { documentDisplayRef } from "@/lib/format";
import type { Invoice } from "@/api/types";

function statusIcon(status: TransactionAuthStep["status"]) {
  if (status === "Done") return CheckCircle2;
  if (status === "Failed") return CircleAlert;
  if (status === "Pending") return Clock3;
  return ShieldCheck;
}

export function TransactionAuthDialog({
  open,
  onClose,
  inv,
  auth,
}: {
  open: boolean;
  onClose: () => void;
  inv: Invoice | null;
  auth: TransactionAuthView | null;
}) {
  const [mounted, setMounted] = useState(false);
  const [dialogState, setDialogState] = useState<"open" | "closed">("closed");
  const [selectedKind, setSelectedKind] = useState<TransactionAuthKind | null>(null);

  useEffect(() => {
    if (open) {
      setMounted(true);
      setSelectedKind(null);
      setDialogState("closed");
      const frame = requestAnimationFrame(() => {
        requestAnimationFrame(() => setDialogState("open"));
      });
      return () => cancelAnimationFrame(frame);
    }
    setDialogState("closed");
    const timer = window.setTimeout(() => setMounted(false), 220);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!mounted) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (selectedKind) {
        setSelectedKind(null);
        return;
      }
      onClose();
    };
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [mounted, onClose, selectedKind]);

  if (!mounted || !inv || !auth) return null;

  const docRef = documentDisplayRef(inv);
  const selected = selectedKind
    ? auth.steps.find((s) => s.kind === selectedKind) ?? null
    : null;

  return createPortal(
    <div
      className="app-modal-root app-modal-root--blur-strong"
      data-testid="transaction-auth-dialog"
      data-state={dialogState}
      role="presentation"
    >
      <button
        type="button"
        className="app-modal-backdrop"
        aria-label="Dismiss"
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="transaction-auth-title"
        className="app-modal-panel w-full max-w-md p-0 overflow-hidden"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 px-5 pt-5 pb-3 border-b border-border/70">
          <div className="min-w-0 flex items-start gap-3">
            {selected ? (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="shrink-0 -ml-1"
                aria-label="Back to pending list"
                onClick={() => setSelectedKind(null)}
              >
                <ArrowLeft className="h-4 w-4" />
              </Button>
            ) : (
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-border bg-muted/50 text-foreground">
                <ShieldCheck className="h-5 w-5" aria-hidden />
              </div>
            )}
            <div className="min-w-0">
              <h2 id="transaction-auth-title" className="text-base font-semibold tracking-tight">
                {selected ? selected.label : "Transaction Auth"}
              </h2>
              <p className="text-xs text-muted-foreground mt-0.5 truncate">
                {docRef}
                {inv.vendor ? ` · ${inv.vendor}` : ""}
              </p>
            </div>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            className="shrink-0"
            aria-label="Close"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="px-5 py-4 space-y-3">
          {selected ? (
            <div className="space-y-3" data-testid={`transaction-auth-detail-${selected.kind}`}>
              <div className="flex flex-wrap items-center gap-2">
                <TableStatusTag
                  tone={authSyncStatusTone(selected.status === "NA" ? "—" : selected.status)}
                  title={selected.status}
                >
                  {selected.status}
                </TableStatusTag>
                <span className="text-xs text-muted-foreground">{selected.detail}</span>
              </div>
              <Card className="p-4 border ds-warning-panel">
                <p className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground mb-1.5">
                  What to do
                </p>
                <p className="text-sm leading-relaxed text-foreground">{selected.actionNeeded}</p>
              </Card>
            </div>
          ) : (
            <>
              <p className="text-xs text-muted-foreground">
                Privilege → Advance → Budget. Select any authorization to see what applies and what to do.
              </p>
              <ul className="space-y-2">
                {auth.steps.map((step) => {
                  const Icon = statusIcon(step.status);
                  const isNext = auth.primaryPending?.kind === step.kind;
                  return (
                    <li key={step.kind}>
                      <button
                        type="button"
                        className={cn(
                          "w-full text-left rounded-lg border p-3 transition-colors",
                          "hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          isNext && "ds-warning-panel border-[hsl(var(--warning-border)/0.45)]"
                        )}
                        data-testid={`transaction-auth-step-${step.kind}`}
                        onClick={() => setSelectedKind(step.kind)}
                      >
                        <div className="flex items-start gap-3">
                          <span
                            className={cn(
                              "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border",
                              isNext
                                ? "ds-warning-badge"
                                : "border-border bg-muted/40 text-muted-foreground"
                            )}
                          >
                            <Icon className="h-4 w-4" aria-hidden />
                          </span>
                          <div className="min-w-0 flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-medium">{step.label}</span>
                              <TableStatusTag
                                tone={authSyncStatusTone(
                                  step.status === "NA" ? "—" : step.status
                                )}
                                title={step.status}
                              >
                                {step.status}
                              </TableStatusTag>
                              {isNext ? (
                                <span className="text-[10px] font-semibold uppercase tracking-wide ds-warning-text">
                                  First pending
                                </span>
                              ) : null}
                            </div>
                            <p className="text-xs text-muted-foreground mt-1">{step.detail}</p>
                          </div>
                          <ChevronRight
                            className="h-4 w-4 shrink-0 text-muted-foreground mt-2"
                            aria-hidden
                          />
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-border/70 bg-muted/20">
          {selected ? (
            <Button type="button" variant="outline" size="sm" onClick={() => setSelectedKind(null)}>
              Back
            </Button>
          ) : null}
          <Button type="button" variant="outline" size="sm" onClick={onClose}>
            Close
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
