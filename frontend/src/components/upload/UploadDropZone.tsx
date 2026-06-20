import { FileUp, Upload } from "lucide-react";
import { useCallback, useRef, useState } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { BULK_UPLOAD_MAX_FILES, UPLOAD_ACCEPT_LABEL } from "@/lib/bulkUpload";
import { cn } from "@/lib/cn";

const FORMAT_TAGS = UPLOAD_ACCEPT_LABEL.split(",").map((s) => s.trim());

type UploadDropZoneProps = {
  disabled?: boolean;
  uploading?: boolean;
  progress?: { completed: number; total: number } | null;
  onFiles: (files: File[]) => void;
  onBrowse: () => void;
  compact?: boolean;
  className?: string;
};

export function UploadDropZone({
  disabled = false,
  uploading = false,
  progress,
  onFiles,
  onBrowse,
  compact = false,
  className,
}: UploadDropZoneProps) {
  const [dragActive, setDragActive] = useState(false);
  const dragDepth = useRef(0);

  const inactive = disabled || uploading;
  const pct =
    progress && progress.total > 0
      ? Math.round((progress.completed / progress.total) * 100)
      : 0;

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
            {progress.completed} / {progress.total}
          </span>
        ) : null}
      </div>

      <div className="p-4">
        <div
          role="button"
          tabIndex={inactive ? -1 : 0}
          aria-label="Drop files to upload or press Enter to browse"
          aria-disabled={inactive}
          className={cn(
            "upload-drop-zone group relative rounded-xl border-2 border-dashed transition-all outline-none",
            "focus-visible:ring-2 focus-visible:ring-primary/40 focus-visible:ring-offset-2",
            compact ? "upload-drop-zone--compact px-4 py-3" : "px-6 py-8",
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
              "flex items-center gap-4",
              compact ? "flex-row text-left" : "flex-col text-center"
            )}
          >
            <div
              className={cn(
                "upload-drop-zone__icon flex shrink-0 items-center justify-center rounded-full border transition-colors",
                compact ? "h-10 w-10" : "h-14 w-14",
                dragActive && !inactive
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border bg-muted/50 text-muted-foreground group-hover:border-primary/30 group-hover:text-primary"
              )}
            >
              {dragActive && !inactive ? (
                <FileUp className={cn(compact ? "h-5 w-5" : "h-6 w-6")} aria-hidden />
              ) : (
                <Upload className={cn(compact ? "h-5 w-5" : "h-6 w-6")} aria-hidden />
              )}
            </div>

            <div className={cn("min-w-0 flex-1", !compact && "w-full")}>
              {uploading && progress ? (
                <>
                  <p className={cn("font-medium text-foreground", compact ? "text-sm" : "text-base")}>
                    Uploading documents…
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Processing starts automatically when the batch finishes
                  </p>
                  <div className={cn("mt-3", compact ? "max-w-full" : "max-w-md mx-auto")}>
                    <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-primary transition-[width] duration-300 ease-out"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <p className={cn("font-medium text-foreground", compact ? "text-sm" : "text-base")}>
                    {dragActive ? "Release to upload" : "Drop files here"}
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    {dragActive
                      ? "Files will upload and enter the capture pipeline"
                      : "Drag invoices from your desktop, or choose files below"}
                  </p>
                  {!compact ? (
                    <div className="flex flex-wrap justify-center gap-1.5 mt-4">
                      {FORMAT_TAGS.map((tag) => (
                        <span
                          key={tag}
                          className="rounded-md border border-border bg-background px-2 py-0.5 text-[10px] font-medium text-muted-foreground"
                        >
                          {tag}
                        </span>
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
                className={cn("shrink-0", compact ? "" : "mt-1")}
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
