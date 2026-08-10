import {
  Check,
  CheckCircle,
  CloudArrowUp,
  FileArrowUp,
  FileText,
  Upload,
  WarningCircle,
  X,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BULK_UPLOAD_MAX_FILES, UPLOAD_ACCEPT_LABEL } from "@/lib/bulkUpload";
import { cn } from "@/lib/cn";
import type { SimpleIcon } from "simple-icons";
import { siAdobeacrobatreader, siJpeg, siMicrosoftword } from "simple-icons";

const FORMAT_TAGS = UPLOAD_ACCEPT_LABEL.split(",").map((s) => s.trim());
const VISIBLE_FILE_ROWS = 3;

const FILE_TYPE_ICONS: Record<string, SimpleIcon | null> = {
  PDF: siAdobeacrobatreader,
  JPG: siJpeg,
  JPEG: siJpeg,
  PNG: null,
  DOCX: siMicrosoftword,
};

function FileTypeTag({ label }: { label: string }) {
  const icon = FILE_TYPE_ICONS[label.toUpperCase()] ?? null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
      {icon ? (
        <svg
          viewBox="0 0 24 24"
          xmlns="http://www.w3.org/2000/svg"
          aria-hidden
          className="h-3 w-3"
        >
          <path fill={`#${icon.hex}`} style={{ fill: `#${icon.hex}` }} d={icon.path} />
        </svg>
      ) : null}
      <span>{label}</span>
    </span>
  );
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const kb = bytes / 1024;
  if (kb < 1024) return `${kb < 10 ? kb.toFixed(1) : Math.round(kb)} KB`;
  const mb = kb / 1024;
  if (mb < 1024) return `${mb < 10 ? mb.toFixed(2) : Math.round(mb)} MB`;
  const gb = mb / 1024;
  return `${gb.toFixed(2)} GB`;
}

type FileRowState = "done" | "active" | "queued" | "failed";

type UploadDropZoneProps = {
  disabled?: boolean;
  uploading?: boolean;
  progress?: { completed: number; total: number } | null;
  files?: File[];
  onFiles: (files: File[]) => void;
  onBrowse: () => void;
  compact?: boolean;
  className?: string;
};

/** Single overall batch bar — fill advances with file count + in-file percent. */
function OverallUploadProgress({
  completed,
  total,
  percent,
}: {
  completed: number;
  total: number;
  percent: number;
}) {
  const fill = Math.max(2, Math.min(100, percent));
  return (
    <div
      className="upload-overall-progress"
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={percent}
      aria-label={`Upload progress ${completed} of ${total} files, ${percent}%`}
    >
      <div className="upload-overall-progress__track">
        <div
          className={cn(
            "upload-overall-progress__fill",
            percent >= 100 && "upload-overall-progress__fill--done"
          )}
          style={{ width: `${fill}%` }}
        />
      </div>
    </div>
  );
}

function UploadFileStatusRow({
  file,
  state,
}: {
  file: { name: string; size?: number };
  state: FileRowState;
}) {
  const size = typeof file.size === "number" ? file.size : 0;

  return (
    <li
      className={cn(
        "upload-file-status",
        state === "done" && "upload-file-status--done",
        state === "active" && "upload-file-status--active",
        state === "queued" && "upload-file-status--queued",
        state === "failed" && "upload-file-status--failed"
      )}
    >
      <FileText
        size={15}
        weight={state === "done" ? "duotone" : "regular"}
        className="upload-file-status__icon"
        aria-hidden
      />
      <div className="upload-file-status__body min-w-0">
        <div className="upload-file-status__top">
          <p className="upload-file-status__name truncate" title={file.name}>
            {file.name}
          </p>
          {state === "done" ? (
            <span className="upload-file-status__meta tnum shrink-0">{formatBytes(size)}</span>
          ) : state === "failed" ? (
            <span className="upload-file-status__error shrink-0">Failed</span>
          ) : state === "queued" ? (
            <span className="upload-file-status__meta shrink-0">Queued</span>
          ) : (
            <span className="upload-file-status__meta shrink-0">Uploading</span>
          )}
        </div>
      </div>
      <span className="upload-file-status__action shrink-0" aria-hidden>
        {state === "done" ? (
          <Check size={14} weight="bold" className="text-emerald-500" />
        ) : state === "active" ? (
          <span className="upload-file-status__cancel">
            <X size={10} weight="bold" />
          </span>
        ) : state === "failed" ? (
          <WarningCircle size={14} weight="fill" className="text-destructive" />
        ) : (
          <span className="h-3.5 w-3.5" />
        )}
      </span>
    </li>
  );
}

export function UploadDropZone({
  disabled = false,
  uploading = false,
  progress,
  files = [],
  onFiles,
  onBrowse,
  compact = false,
  className,
}: UploadDropZoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const dragDepth = useRef(0);
  const [activePct, setActivePct] = useState(0);

  const inactive = disabled || uploading;
  const completed = progress?.completed ?? 0;
  const total = progress?.total ?? Math.max(files.length, 0);
  const overallPct =
    uploading && total > 0
      ? Math.min(
          99,
          Math.max(0, Math.floor(((completed + activePct / 100) / total) * 100))
        )
      : total > 0
        ? 100
        : 0;

  const fileList = useMemo(() => {
    if (files.length > 0) return files.slice(0, total || files.length);
    return Array.from({ length: total }, (_, i) => ({
      name: `File ${i + 1}`,
      size: 0,
    }));
  }, [files, total]);

  const visibleWindow = useMemo(() => {
    if (fileList.length === 0) return [] as { file: (typeof fileList)[number]; index: number }[];
    const maxStart = Math.max(0, fileList.length - VISIBLE_FILE_ROWS);
    // Keep active file in the middle band when possible.
    const preferred = Math.max(0, completed - 1);
    const start = Math.min(preferred, maxStart);
    return fileList.slice(start, start + VISIBLE_FILE_ROWS).map((file, offset) => ({
      file,
      index: start + offset,
    }));
  }, [fileList, completed]);

  useEffect(() => {
    if (!uploading || !progress || progress.total <= 0) {
      setActivePct(0);
      return;
    }
    setActivePct(8);
    const t = window.setInterval(() => {
      setActivePct((p) => {
        if (!uploading) return 0;
        const next = p < 70 ? p + 2.4 : p < 90 ? p + 0.9 : p + 0.25;
        return Math.min(96, next);
      });
    }, 110);
    return () => window.clearInterval(t);
  }, [uploading, progress?.completed, progress?.total]);

  const handleDragEnter = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (inactive) return;
      dragDepth.current += 1;
      setDragActive(true);
    },
    [inactive]
  );

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragDepth.current = Math.max(0, dragDepth.current - 1);
    if (dragDepth.current === 0) {
      setDragActive(false);
    }
  }, []);

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      if (inactive) return;
      e.dataTransfer.dropEffect = "copy";
    },
    [inactive]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      dragDepth.current = 0;
      setDragActive(false);
      if (inactive) return;
      const dropped = Array.from(e.dataTransfer.files ?? []);
      if (dropped.length > 0) {
        onFiles(dropped);
      }
    },
    [inactive, onFiles]
  );

  const openBrowse = useCallback(() => {
    if (!inactive) onBrowse();
  }, [inactive, onBrowse]);

  const showProgress = Boolean(uploading && progress && total > 0);

  return (
    <Card className={cn("overflow-hidden", className)} data-testid="upload-drop-zone-card">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Upload size={16} className="text-primary shrink-0" weight="duotone" />
          Manual upload
        </h3>
        {!showProgress ? (
          <span className="text-xs text-muted-foreground hidden sm:inline">
            Up to {BULK_UPLOAD_MAX_FILES} files per batch
          </span>
        ) : (
          <span className="text-xs text-muted-foreground tnum tabular-nums">
            {completed} / {total}
          </span>
        )}
      </div>

      <div className="p-5">
        <div
          role={showProgress ? "status" : "button"}
          tabIndex={showProgress || inactive ? -1 : 0}
          aria-label={
            showProgress
              ? `Uploading files, ${completed} of ${total} done`
              : "Drop files to upload or press Enter to browse"
          }
          aria-disabled={inactive}
          aria-live={showProgress ? "polite" : undefined}
          className={cn(
            "upload-drop-zone group relative rounded-xl border-2 transition-all outline-none",
            "focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2",
            showProgress
              ? "upload-drop-zone--progressing border-solid px-5 py-5"
              : cn(
                  "border-dashed",
                  compact ? "upload-drop-zone--compact px-4 py-3" : "px-6 py-6"
                ),
            dragActive && !inactive && "upload-drop-zone--active",
            !inactive && !uploading && "cursor-pointer hover:border-primary/40 hover:bg-muted/30",
            disabled && !uploading && "opacity-70 pointer-events-none",
            uploading && "pointer-events-none"
          )}
          onDragEnter={showProgress ? undefined : handleDragEnter}
          onDragLeave={showProgress ? undefined : handleDragLeave}
          onDragOver={showProgress ? undefined : handleDragOver}
          onDrop={showProgress ? undefined : handleDrop}
          onClick={showProgress ? undefined : openBrowse}
          onKeyDown={(e) => {
            if (showProgress || inactive) return;
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              openBrowse();
            }
          }}
          data-testid="upload-drop-zone"
        >
          {showProgress ? (
            completed >= total ? (
              <div
                className="upload-progress-success"
                data-testid="upload-progress-success"
                role="status"
              >
                <span className="upload-progress-success__icon" aria-hidden>
                  <CheckCircle size={56} weight="fill" />
                </span>
                <p className="upload-progress-success__title">All files uploaded</p>
                <p className="upload-progress-success__sub">
                  Successfully uploaded all {total} file{total === 1 ? "" : "s"}
                </p>
              </div>
            ) : (
            <div className="upload-progress-panel" data-testid="upload-progress-panel">
              <div className="upload-progress-hero">
                <div className="upload-progress-hero__copy">
                  <p className="upload-progress-hero__eyebrow">
                    <span className="upload-progress-hero__pulse" aria-hidden />
                    {completed >= total ? "Almost there" : "Uploading batch"}
                  </p>
                  <p className="upload-progress-hero__title">
                    <span className="upload-progress-hero__num tnum tabular-nums">
                      {completed}
                    </span>
                    <span className="upload-progress-hero__of"> of </span>
                    <span className="upload-progress-hero__num upload-progress-hero__num--total tnum tabular-nums">
                      {total}
                    </span>
                    <span className="upload-progress-hero__label"> files done</span>
                    <span className="upload-progress-hero__pct tnum tabular-nums">
                      {" "}
                      · {overallPct}%
                    </span>
                  </p>
                  <p className="upload-progress-hero__sub">
                    {completed >= total
                      ? "Wrapping up your batch…"
                      : `File ${Math.min(completed + 1, total)} is moving through now`}
                  </p>
                </div>
              </div>

              <OverallUploadProgress
                completed={completed}
                total={total}
                percent={overallPct}
              />

              <div className="upload-progress-files">
                <div className="upload-progress-files__head">
                  <p className="upload-progress-files__title">Live queue</p>
                  <span className="upload-progress-files__count tnum">
                    {Math.min(VISIBLE_FILE_ROWS, fileList.length)} showing
                  </span>
                </div>
                <div className="upload-progress-files__viewport">
                  <ul className="upload-progress-files__list" data-testid="upload-progress-files">
                    {visibleWindow.map(({ file, index }) => {
                      const state: FileRowState =
                        index < completed ? "done" : index === completed ? "active" : "queued";
                      return (
                        <UploadFileStatusRow
                          key={`${index}-${file.name}`}
                          file={file}
                          state={state}
                        />
                      );
                    })}
                  </ul>
                  {fileList.length > 2 ? (
                    <div className="upload-progress-files__fade" aria-hidden />
                  ) : null}
                </div>
              </div>
            </div>
            )
          ) : (
            <div
              className={cn(
                "flex items-center",
                compact ? "flex-row gap-4 text-left" : "flex-col gap-3 text-center"
              )}
            >
              <div className={cn("min-w-0", compact && "flex-1")}>
                <div
                  className={cn(
                    "upload-drop-zone__icon mx-auto flex shrink-0 items-center justify-center transition-colors",
                    compact ? "h-10 w-10" : "h-12 w-12",
                    dragActive && !inactive
                      ? "text-primary"
                      : "text-muted-foreground group-hover:text-primary"
                  )}
                >
                  {dragActive && !inactive ? (
                    <FileArrowUp size={compact ? 20 : 24} weight="duotone" aria-hidden />
                  ) : (
                    <CloudArrowUp size={compact ? 20 : 24} weight="duotone" aria-hidden />
                  )}
                </div>
                <p className={cn("font-medium text-foreground", compact ? "text-sm" : "text-base")}>
                  {dragActive ? "Release to upload" : "Drop files here"}
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  {dragActive
                    ? "Files will upload and enter the capture pipeline"
                    : "Drag invoices from your desktop, or choose files below"}
                </p>
                {!compact ? (
                  <div className="flex flex-wrap justify-center gap-1.5 mt-3">
                    {FORMAT_TAGS.map((tag) => (
                      <FileTypeTag key={tag} label={tag} />
                    ))}
                  </div>
                ) : null}
              </div>

              <Button
                type="button"
                size="sm"
                className="shrink-0"
                onClick={(e) => {
                  e.stopPropagation();
                  openBrowse();
                }}
                data-testid="button-upload-doc"
              >
                Choose files
              </Button>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}
