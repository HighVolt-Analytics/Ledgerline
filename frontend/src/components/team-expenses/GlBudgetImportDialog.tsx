import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Download, FileSpreadsheet, Loader2, Upload, X } from "lucide-react";
import type { DepartmentBudgetImportResult } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, toSelectOptions } from "@/components/ui/select";
import { FieldLabel } from "@/components/rule-book/FieldLabel";

type Step = "pick" | "preview";
type PeriodKind = "monthly" | "quarterly" | "annual";

function currentPeriodKey(kind: PeriodKind): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = now.getMonth() + 1;
  if (kind === "monthly") return `${y}-${String(m).padStart(2, "0")}`;
  if (kind === "quarterly") return `${y}-Q${Math.floor((m - 1) / 3) + 1}`;
  return `${y}`;
}

export function GlBudgetImportDialog({
  open,
  busy,
  onClose,
  onDownloadTemplate,
  onPreview,
  onImport,
}: {
  open: boolean;
  busy: boolean;
  onClose: () => void;
  onDownloadTemplate: (opts: {
    period_kind: PeriodKind;
    period_key: string;
  }) => Promise<void>;
  onPreview: (file: File) => Promise<DepartmentBudgetImportResult>;
  onImport: (file: File) => Promise<DepartmentBudgetImportResult>;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [periodKind, setPeriodKind] = useState<PeriodKind>("monthly");
  const [periodKey, setPeriodKey] = useState(currentPeriodKey("monthly"));
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<Step>("pick");
  const [preview, setPreview] = useState<DepartmentBudgetImportResult | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);

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
  }, [open, busy, onClose]);

  const reset = () => {
    setFile(null);
    setStep("pick");
    setPreview(null);
    setLocalError(null);
    if (inputRef.current) inputRef.current.value = "";
  };

  const close = () => {
    if (busy) return;
    reset();
    onClose();
  };

  const handlePreview = async () => {
    if (!file) return;
    setLocalError(null);
    try {
      const result = await onPreview(file);
      setPreview(result);
      setStep("preview");
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Failed to review import file");
    }
  };

  const handleImport = async () => {
    if (!file) return;
    setLocalError(null);
    try {
      await onImport(file);
      reset();
      onClose();
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Import failed");
    }
  };

  if (!open) return null;

  return createPortal(
    <div className="v5-dialog-root" role="presentation">
      <button
        type="button"
        className="v5-dialog-overlay"
        aria-label="Close import dialog"
        disabled={busy}
        onClick={close}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="gl-budget-import-title"
        className="v5-dialog-content max-w-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 -mt-1">
          <div>
            <h2 id="gl-budget-import-title" className="text-sm font-semibold">
              Import GL budgets
            </h2>
            <p className="text-xs text-muted-foreground mt-1">
              Download a template prefilled from your chart of accounts, fill Allocated amounts,
              then upload. Parent + Sub-GL rows are saved as one wallet tree per period.
            </p>
          </div>
          <button
            type="button"
            onClick={close}
            disabled={busy}
            className="rounded-sm opacity-70 hover:opacity-100 disabled:opacity-40"
            aria-label="Close"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="grid gap-2 sm:grid-cols-2">
          <FieldLabel label="Template period kind">
            <Select
              value={periodKind}
              onValueChange={(v) => {
                const kind = (["monthly", "quarterly", "annual"].includes(v)
                  ? v
                  : "monthly") as PeriodKind;
                setPeriodKind(kind);
                setPeriodKey(currentPeriodKey(kind));
              }}
              options={toSelectOptions(["monthly", "quarterly", "annual"])}
              className="h-8 text-xs"
              disabled={busy || step === "preview"}
            />
          </FieldLabel>
          <FieldLabel label="Template period key">
            <Input
              value={periodKey}
              onChange={(e) => setPeriodKey(e.target.value)}
              placeholder="2026-08 / 2026-Q3 / 2026"
              className="h-8 text-xs"
              disabled={busy || step === "preview"}
            />
          </FieldLabel>
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy || downloading || !periodKey.trim()}
            onClick={async () => {
              setDownloading(true);
              setLocalError(null);
              try {
                await onDownloadTemplate({
                  period_kind: periodKind,
                  period_key: periodKey.trim(),
                });
              } catch (err) {
                setLocalError(
                  err instanceof Error ? err.message : "Failed to download template"
                );
              } finally {
                setDownloading(false);
              }
            }}
            data-testid="button-gl-budget-download-template"
          >
            {downloading ? (
              <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5 mr-1" />
            )}
            Download template
          </Button>
          <input
            ref={inputRef}
            type="file"
            accept=".csv,.xlsx"
            className="hidden"
            disabled={busy}
            onChange={(e) => {
              const picked = e.target.files?.[0] ?? null;
              setFile(picked);
              setStep("pick");
              setPreview(null);
              setLocalError(null);
            }}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
            data-testid="button-gl-budget-choose-file"
          >
            <Upload className="h-3.5 w-3.5 mr-1" />
            {file ? file.name : "Choose file"}
          </Button>
        </div>

        {localError ? (
          <p className="text-xs text-destructive" role="alert">
            {localError}
          </p>
        ) : null}

        {step === "preview" && preview && (
          <div className="rounded-md border border-border bg-muted/20 p-3 space-y-2 text-xs">
            <p className="font-medium flex items-center gap-1.5">
              <FileSpreadsheet className="h-3.5 w-3.5" />
              Preview — no changes saved yet
            </p>
            <p className="text-muted-foreground">
              {preview.created} create · {preview.updated} update · {preview.skipped} skip
              {preview.errors.length > 0 ? ` · ${preview.errors.length} error(s)` : ""}
            </p>
            {preview.errors.length > 0 && (
              <ul className="text-destructive space-y-0.5 max-h-24 overflow-y-auto">
                {preview.errors.slice(0, 10).map((err) => (
                  <li key={`${err.row_number}-${err.message}`}>
                    Row {err.row_number}
                    {err.parent_gl ? ` (${err.parent_gl})` : ""}: {err.message}
                  </li>
                ))}
              </ul>
            )}
            {preview.previews.length > 0 && (
              <ul className="text-muted-foreground space-y-0.5 max-h-32 overflow-y-auto">
                {preview.previews.slice(0, 14).map((row) => (
                  <li key={`${row.row_number}-${row.parent_gl}-${row.period_key}`}>
                    Row {row.row_number}: {row.action} {row.parent_gl} · {row.period_kind}{" "}
                    {row.period_key}
                    {row.detail ? ` — ${row.detail}` : ""}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className="flex flex-wrap gap-2 justify-end">
          <Button variant="outline" size="sm" disabled={busy} onClick={close}>
            Cancel
          </Button>
          {step === "pick" ? (
            <Button
              size="sm"
              disabled={busy || !file}
              onClick={() => void handlePreview()}
              data-testid="button-gl-budget-review-import"
            >
              {busy ? (
                <>
                  <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                  Checking…
                </>
              ) : (
                "Review import"
              )}
            </Button>
          ) : (
            <>
              <Button
                variant="outline"
                size="sm"
                disabled={busy}
                onClick={() => {
                  setStep("pick");
                  setPreview(null);
                }}
              >
                Back
              </Button>
              <Button
                size="sm"
                disabled={busy || !file || !preview || preview.created + preview.updated === 0}
                onClick={() => void handleImport()}
                data-testid="button-gl-budget-confirm-import"
              >
                {busy ? (
                  <>
                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                    Importing…
                  </>
                ) : (
                  "Import"
                )}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>,
    document.body
  );
}
