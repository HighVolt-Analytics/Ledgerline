import { useEffect } from "react";
import { createPortal } from "react-dom";
import { CalendarRange, Download, FileSpreadsheet, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/cn";

export type ExportWorkbookMode = "range" | "all";

const WORKBOOK_SHEETS = [
  "Invoices",
  "Line Items",
  "Ledger Mapping",
  "Journal Entries",
  "Daily Reconciliation",
  "Expense Summary",
  "Processing Status",
  "Rule Book",
];

type ExportWorkbookDialogProps = {
  open: boolean;
  onClose: () => void;
  exportMode: ExportWorkbookMode;
  onExportModeChange: (mode: ExportWorkbookMode) => void;
  dateFrom: string;
  dateTo: string;
  onDateFromChange: (value: string) => void;
  onDateToChange: (value: string) => void;
  exportCount: number;
  totalDocuments: number;
  rangeInvalid: boolean;
  busy: boolean;
  onExport: () => void;
};

export function ExportWorkbookDialog({
  open,
  onClose,
  exportMode,
  onExportModeChange,
  dateFrom,
  dateTo,
  onDateFromChange,
  onDateToChange,
  exportCount,
  totalDocuments,
  rangeInvalid,
  busy,
  onExport,
}: ExportWorkbookDialogProps) {
  useEffect(() => {
    if (!open) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !busy) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, busy]);

  if (!open) return null;

  const canExport = !rangeInvalid && !busy;

  return createPortal(
    <div className="app-modal-root" role="presentation">
      <button
        type="button"
        className="app-modal-backdrop"
        aria-label="Close export dialog"
        onClick={onClose}
        disabled={busy}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="export-workbook-title"
        className="app-modal-panel export-csv-dialog p-6 space-y-5"
        data-testid="export-workbook-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
            <FileSpreadsheet className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex items-start justify-between gap-2">
              <h2 id="export-workbook-title" className="text-lg font-semibold leading-none">
                Export workbook
              </h2>
              <button
                type="button"
                onClick={onClose}
                disabled={busy}
                className="rounded-sm p-1 opacity-70 hover:opacity-100 transition-opacity shrink-0 -mt-0.5"
                aria-label="Close"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <p className="text-sm text-muted-foreground mt-2">
              Download the full Excel report with {WORKBOOK_SHEETS.length} sheets — invoices,
              journal entries, reconciliation, expense summary, rule book, and more.
            </p>
          </div>
        </div>

        <div className="rounded-lg border border-border bg-muted/15 px-3 py-2.5">
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground mb-1.5">
            Workbook tabs
          </p>
          <p className="text-xs text-muted-foreground leading-relaxed">
            {WORKBOOK_SHEETS.join(" · ")}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-1 p-1 rounded-lg bg-muted/50 border border-border/60">
          <button
            type="button"
            className={cn(
              "flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-all",
              exportMode === "range"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
            onClick={() => onExportModeChange("range")}
            data-testid="export-mode-range"
          >
            <CalendarRange className="h-3.5 w-3.5" />
            Date range
          </button>
          <button
            type="button"
            className={cn(
              "flex items-center justify-center gap-1.5 px-3 py-2 rounded-md text-sm font-medium transition-all",
              exportMode === "all"
                ? "bg-background text-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground"
            )}
            onClick={() => onExportModeChange("all")}
            data-testid="export-mode-all"
          >
            All dates
          </button>
        </div>

        {exportMode === "range" ? (
          <div className="rounded-lg border border-border bg-muted/20 p-4 space-y-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Invoice date range
            </p>
            <div className="grid sm:grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="export-date-from">
                  From
                </label>
                <Input
                  id="export-date-from"
                  type="date"
                  value={dateFrom}
                  onChange={(e) => onDateFromChange(e.target.value)}
                  className="h-9 bg-background"
                  data-testid="export-date-from"
                  disabled={busy}
                />
              </div>
              <div className="space-y-1.5">
                <label className="text-sm font-medium" htmlFor="export-date-to">
                  To
                </label>
                <Input
                  id="export-date-to"
                  type="date"
                  value={dateTo}
                  onChange={(e) => onDateToChange(e.target.value)}
                  className="h-9 bg-background"
                  data-testid="export-date-to"
                  disabled={busy}
                />
              </div>
            </div>
            {rangeInvalid && (
              <p className="text-sm text-destructive" role="alert">
                From date must be on or before to date.
              </p>
            )}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border bg-muted/15 px-4 py-3 text-sm text-muted-foreground">
            All {totalDocuments.toLocaleString()} processed document
            {totalDocuments === 1 ? "" : "s"} in your organisation will be included.
          </div>
        )}

        <div
          className={cn(
            "flex items-center justify-between rounded-lg px-4 py-3 text-sm border",
            exportCount > 0
              ? "bg-primary/5 border-primary/20"
              : "bg-muted/30 border-border/60"
          )}
        >
          <span className="text-muted-foreground">Invoices in selection</span>
          <span className="font-semibold tnum">
            {rangeInvalid ? "—" : exportCount.toLocaleString()}
          </span>
        </div>

        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            disabled={!canExport}
            onClick={onExport}
            data-testid="button-download-workbook"
          >
            <Download className="h-4 w-4 mr-1.5" />
            {busy ? "Generating…" : "Download workbook"}
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
