import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Download, FileSpreadsheet, Loader2, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/cn";
import type { EmployeeImportMode, EmployeeImportResult } from "@/api/client";

type Step = "pick" | "preview";

export function EmployeeImportDialog({
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
  onDownloadTemplate: (mode: EmployeeImportMode) => Promise<void>;
  onPreview: (mode: EmployeeImportMode, file: File) => Promise<EmployeeImportResult>;
  onImport: (mode: EmployeeImportMode, file: File) => Promise<EmployeeImportResult>;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<EmployeeImportMode>("register");
  const [file, setFile] = useState<File | null>(null);
  const [step, setStep] = useState<Step>("pick");
  const [preview, setPreview] = useState<EmployeeImportResult | null>(null);
  const [downloading, setDownloading] = useState(false);

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
    if (inputRef.current) inputRef.current.value = "";
  };

  const close = () => {
    if (busy) return;
    reset();
    onClose();
  };

  const handlePreview = async () => {
    if (!file) return;
    const result = await onPreview(mode, file);
    setPreview(result);
    setStep("preview");
  };

  const handleImport = async () => {
    if (!file) return;
    await onImport(mode, file);
    reset();
    onClose();
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
        aria-labelledby="employee-import-title"
        className="v5-dialog-content max-w-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 -mt-1">
          <div>
            <h2 id="employee-import-title" className="text-sm font-semibold">
              Import employees
            </h2>
            <p className="text-xs text-muted-foreground mt-1">
              Use separate templates for staff register (identity) and payment details (bank and
              budget). Rows are matched by work email.
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

        <div className="flex gap-2">
          {(["register", "payment"] as const).map((value) => (
            <button
              key={value}
              type="button"
              disabled={busy || step === "preview"}
              className={cn(
                "flex-1 rounded-md border px-3 py-2 text-xs text-left transition-colors",
                mode === value
                  ? "border-primary bg-primary/5 text-foreground"
                  : "border-border text-muted-foreground hover:bg-muted/40"
              )}
              onClick={() => {
                setMode(value);
                reset();
              }}
            >
              <span className="font-medium block">
                {value === "register" ? "Register" : "Payment"}
              </span>
              <span className="text-[11px] opacity-80">
                {value === "register"
                  ? "Name, email, WhatsApp, role, status"
                  : "Bank, budget, status by email"}
              </span>
            </button>
          ))}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy || downloading}
            onClick={async () => {
              setDownloading(true);
              try {
                await onDownloadTemplate(mode);
              } finally {
                setDownloading(false);
              }
            }}
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
            }}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            <Upload className="h-3.5 w-3.5 mr-1" />
            {file ? file.name : "Choose file"}
          </Button>
        </div>

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
                {preview.errors.slice(0, 8).map((err) => (
                  <li key={`${err.row_number}-${err.message}`}>
                    Row {err.row_number}
                    {err.email ? ` (${err.email})` : ""}: {err.message}
                  </li>
                ))}
              </ul>
            )}
            {preview.previews.length > 0 && (
              <ul className="text-muted-foreground space-y-0.5 max-h-32 overflow-y-auto">
                {preview.previews.slice(0, 12).map((row) => (
                  <li key={`${row.row_number}-${row.email}`}>
                    Row {row.row_number}: {row.action} {row.email}
                    {row.name ? ` — ${row.name}` : ""}
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
            <Button size="sm" disabled={busy || !file} onClick={() => void handlePreview()}>
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
