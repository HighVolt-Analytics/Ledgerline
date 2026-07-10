import { Check, CloudUpload, FileUp, Loader2, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BULK_UPLOAD_MAX_FILES, UPLOAD_ACCEPT_LABEL } from "@/lib/bulkUpload";
import { cn } from "@/lib/cn";
import type { SimpleIcon } from "simple-icons";
import { siAdobeacrobatreader, siJpeg, siMicrosoftword } from "simple-icons";

const FORMAT_TAGS = UPLOAD_ACCEPT_LABEL.split(",").map((s) => s.trim());

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

  useEffect(() => {
    if (!uploading || !progress || progress.total <= 0) {
      setActivePct(0);
      return;
    }
    setActivePct(0);
    const t = window.setInterval(() => {
      setActivePct((p) => {
        if (!uploading) return 0;
        // Ease out; keep moving but never "finish" until completion increments.
        const next = p < 92 ? p + 3 : p < 97 ? p + 1 : p;
        return Math.min(98, next);
      });
    }, 120);
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

  return (
    <Card className={cn("overflow-hidden", className)} data-testid="upload-drop-zone-card">
      <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-border">
        <h3 className="text-sm font-semibold flex items-center gap-2">
          <Upload className="h-4 w-4 text-primary shrink-0" />
          Manual upload
        </h3>
        {!uploading ? (
          <span className="text-xs text-muted-foreground hidden sm:inline">
            Up to {BULK_UPLOAD_MAX_FILES} files per batch
          </span>
        ) : progress ? (
          <span className="text-xs text-muted-foreground tnum">
            {overallPct}% · {completed} done
          </span>
        ) : null}
      </div>

      <div className="p-5">
        <div
          role="button"
          tabIndex={inactive ? -1 : 0}
          aria-label="Drop files to upload or press Enter to browse"
          aria-disabled={inactive}
          className={cn(
            "upload-drop-zone group relative rounded-xl border-2 border-dashed transition-all outline-none",
            "focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2",
            compact ? "upload-drop-zone--compact px-4 py-3" : "px-6 py-6",
            dragActive && !inactive && "upload-drop-zone--active",
            !inactive && !uploading && "cursor-pointer hover:border-primary/40 hover:bg-muted/30",
            inactive && "opacity-70 pointer-events-none"
          )}
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          onClick={openBrowse}
          onKeyDown={(e) => {
            if (inactive) return;
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              openBrowse();
            }
          }}
          data-testid="upload-drop-zone"
        >
          <div
            className={cn(
              "flex items-center",
              compact ? "flex-row gap-4 text-left" : "flex-col gap-3 text-center"
            )}
          >
            <div className={cn("min-w-0", compact && "flex-1")}>
              {uploading && progress ? (
                <>
                  <p className={cn("font-medium text-foreground", compact ? "text-sm" : "text-base")}>
                    Uploading {progress.total} file{progress.total === 1 ? "" : "s"}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {completed} done · {Math.max(0, progress.total - completed)} remaining
                  </p>

                  <div className={cn("mt-3 space-y-3", compact ? "max-w-full" : "max-w-lg mx-auto")}>
                    {(files.length ? files : Array.from({ length: progress.total }, (_, i) => ({ name: `File ${i + 1}` } as File)))
                      .slice(0, progress.total)
                      .map((f, idx) => {
                        const isDone = idx < completed;
                        const isActive = idx === completed;
                        const rowPct = isDone ? 100 : isActive ? activePct : 0;
                        return (
                          <div key={`${idx}-${f.name}`} className="text-left">
                            <div className="flex items-center justify-between gap-3">
                              <div className="min-w-0 flex items-center gap-2">
                                {isDone ? (
                                  <Check className="h-4 w-4 text-[hsl(var(--chart-1))] shrink-0" aria-hidden />
                                ) : isActive ? (
                                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground shrink-0" aria-hidden />
                                ) : (
                                  <span className="h-4 w-4 shrink-0" />
                                )}
                                <span className="text-sm font-medium truncate">{f.name}</span>
                              </div>
                              <span className="text-xs text-muted-foreground tnum shrink-0">
                                {Math.round(rowPct)}%
                              </span>
                            </div>
                            <div className="mt-2 h-2 rounded-full bg-muted overflow-hidden">
                              <div
                                className={cn(
                                  "h-full rounded-full transition-[width] duration-200 ease-out",
                                  isDone ? "bg-[hsl(var(--chart-1))]" : "bg-primary"
                                )}
                                style={{ width: `${rowPct}%` }}
                              />
                            </div>
                          </div>
                        );
                      })}
                  </div>
                </>
              ) : (
                <>
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
                      <FileUp className={cn(compact ? "h-5 w-5" : "h-6 w-6")} aria-hidden />
                    ) : (
                      <CloudUpload className={cn(compact ? "h-5 w-5" : "h-6 w-6")} aria-hidden />
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
                </>
              )}
            </div>

            {!uploading ? (
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
            ) : null}
          </div>
        </div>
      </div>
    </Card>
  );
}
