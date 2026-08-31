import { useRef, useState } from "react";
import { ChevronDown, ChevronUp, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useBankFeedImports, useBankFeedMutations } from "@/hooks/useBankFeeds";
import { ApiError } from "@/api/client";
import {
  formatBankImportFlash,
  parseBankImportErrorReport,
  type BankImportRowError,
} from "@/lib/bankFeedCopy";
import { cn } from "@/lib/cn";

const RECENT_IMPORTS_LIMIT = 5;

function formatImportWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  if (sameDay) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function BankFeedImportSection({
  accountId,
  canPost,
  onImportSuccess,
}: {
  accountId: number | null;
  canPost: boolean;
  onImportSuccess?: (message: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [recentExpanded, setRecentExpanded] = useState(false);
  const [importBanner, setImportBanner] = useState<string | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const [importErrors, setImportErrors] = useState<BankImportRowError[]>([]);
  const [dragDepth, setDragDepth] = useState(0);
  const fileRef = useRef<HTMLInputElement>(null);
  const mutations = useBankFeedMutations();
  const importsQ = useBankFeedImports(accountId, 1, RECENT_IMPORTS_LIMIT, accountId != null);
  const imports = importsQ.data?.data.items ?? [];
  const totalImports = importsQ.data?.meta?.total ?? imports.length;
  const busy = mutations.importCsv.isPending;
  const latestImport = imports[0];

  const onImport = async (file: File) => {
    if (accountId == null) return;
    setImportBanner(null);
    setImportError(null);
    try {
      const result = await mutations.importCsv.mutateAsync({ accountId, file });
      const rowErrors = parseBankImportErrorReport(result.error_report);
      setImportErrors(rowErrors);

      let message: string;
      if (result.reused_existing) {
        message = formatBankImportFlash(result);
      } else {
        const status = (result.status || "").toLowerCase();
        if (status === "partial" || (rowErrors.length > 0 && result.accepted_count > 0)) {
          const categorized =
            typeof result.categorized_count === "number"
              ? ` · ${result.categorized_count} auto-categorized`
              : "";
          message =
            `Partial import: ${result.accepted_count} of ${result.row_count} rows accepted` +
            (rowErrors.length ? ` · ${rowErrors.length} row error(s)` : "") +
            categorized;
        } else if (status === "failed" || (rowErrors.length > 0 && result.accepted_count === 0)) {
          setImportErrors(rowErrors);
          setImportError(
            rowErrors.length
              ? `Import failed with ${rowErrors.length} row error(s)`
              : "Import failed"
          );
          return;
        } else {
          message = formatBankImportFlash(result);
        }
      }
      setImportBanner(message);
      setExpanded(true);
      onImportSuccess?.(message);
    } catch (err) {
      const msg =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Import failed";
      setImportError(msg);
      setImportErrors([]);
      setExpanded(true);
    }
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragDepth(0);
    if (!canPost || busy || accountId == null) return;
    const file = e.dataTransfer.files?.[0];
    if (file) void onImport(file);
  };

  const recentSummary =
    accountId == null
      ? null
      : importsQ.isLoading
        ? "Loading…"
        : latestImport
          ? `Latest: ${latestImport.filename ?? "CSV"} · ${latestImport.accepted_count} rows · ${formatImportWhen(latestImport.imported_at)}`
          : "No imports yet";

  return (
    <Card className="overflow-hidden" data-testid="bf-import-section">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left hover:bg-muted/30 transition-colors"
        onClick={() => setExpanded((v) => !v)}
        data-testid="bf-import-section-toggle"
      >
        <div className="min-w-0">
          <span className="text-sm font-semibold">Import statements</span>
          {!expanded && recentSummary ? (
            <p className="mt-0.5 truncate text-xs text-muted-foreground">{recentSummary}</p>
          ) : null}
        </div>
        {expanded ? (
          <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="space-y-3 border-t border-border px-4 pb-3 pt-3">
          {(importBanner || importError) && (
            <p
              className={
                importError ? "text-sm text-destructive" : "text-sm text-muted-foreground"
              }
              role={importError ? "alert" : "status"}
            >
              {importError || importBanner}
            </p>
          )}

          <div
            className={cn(
              "rounded-md border-2 border-dashed px-4 py-4 text-center transition-colors",
              dragDepth > 0 && "border-[#008abf] bg-[#008abf]/5",
              accountId == null && "opacity-60"
            )}
            onDragEnter={(e) => {
              e.preventDefault();
              setDragDepth((d) => d + 1);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setDragDepth((d) => Math.max(0, d - 1));
            }}
            onDragOver={(e) => e.preventDefault()}
            onDrop={onDrop}
            data-testid="bf-import-dropzone"
          >
            <Upload className="mx-auto mb-1.5 h-6 w-6 text-muted-foreground" />
            <p className="text-sm font-medium">
              {accountId == null
                ? "Select or create a bank account first"
                : "Drop bank CSV here or browse"}
            </p>
            <p className="mt-0.5 text-xs text-muted-foreground">CSV only · 10 MB max</p>
            <Button
              className="mt-2"
              size="sm"
              variant="outline"
              disabled={!canPost || busy || accountId == null}
              onClick={() => fileRef.current?.click()}
              data-testid="bf-import-browse"
            >
              Browse CSV
            </Button>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file) void onImport(file);
              }}
            />
          </div>

          {importErrors.length > 0 && (
            <div
              className="space-y-1 rounded-md border border-destructive/30 p-2.5"
              data-testid="bf-import-errors"
            >
              <p className="text-xs font-medium text-destructive">
                Import row errors ({importErrors.length})
              </p>
              <ul className="max-h-24 space-y-0.5 overflow-y-auto text-xs text-muted-foreground">
                {importErrors.slice(0, 8).map((err, idx) => (
                  <li key={`${err.rowNumber ?? "x"}-${idx}`}>
                    {err.rowNumber != null ? (
                      <span className="tnum font-medium text-foreground">
                        Row {err.rowNumber}:{" "}
                      </span>
                    ) : null}
                    {err.message}
                  </li>
                ))}
                {importErrors.length > 8 ? (
                  <li className="text-muted-foreground">+ {importErrors.length - 8} more</li>
                ) : null}
              </ul>
            </div>
          )}

          {accountId != null && !importsQ.isLoading && imports.length > 0 ? (
            <div className="rounded-md border border-border/70 bg-muted/20">
              <button
                type="button"
                className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left text-xs hover:bg-muted/40"
                onClick={() => setRecentExpanded((v) => !v)}
                data-testid="bf-recent-imports-toggle"
              >
                <span className="font-medium text-muted-foreground">
                  Recent imports
                  {totalImports > 0 ? (
                    <span className="ml-1 tnum text-foreground">({totalImports})</span>
                  ) : null}
                </span>
                {recentExpanded ? (
                  <ChevronUp className="h-3.5 w-3.5 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                )}
              </button>

              {recentExpanded ? (
                <ul className="max-h-36 space-y-0 overflow-y-auto border-t border-border/60 px-3 py-1.5">
                  {imports.map((row) => (
                    <li
                      key={row.id}
                      className="flex items-baseline justify-between gap-3 border-b border-border/40 py-1.5 text-xs last:border-0"
                    >
                      <span className="min-w-0 truncate font-medium" title={row.filename ?? undefined}>
                        {row.filename ?? "—"}
                      </span>
                      <span className="shrink-0 tnum text-muted-foreground">
                        {formatImportWhen(row.imported_at)}
                        <span className="mx-1">·</span>
                        {row.accepted_count} rows
                        {row.error_count > 0 ? (
                          <span className="text-destructive"> · {row.error_count} err</span>
                        ) : null}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}

              {recentExpanded && totalImports > RECENT_IMPORTS_LIMIT ? (
                <p className="border-t border-border/60 px-3 py-1.5 text-[11px] text-muted-foreground">
                  Showing latest {RECENT_IMPORTS_LIMIT} of {totalImports} imports
                </p>
              ) : null}
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}
