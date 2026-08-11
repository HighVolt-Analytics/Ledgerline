import { useCallback, useEffect, useRef, useState } from "react";
import { Download, FileText, Loader2, Minus, Plus, RotateCcw } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { PageTabs } from "@/components/PageTabs";
import { cn } from "@/lib/cn";

export type InvoiceFilePreviewResult = {
  url: string;
  mimeType: string;
  filename: string;
};

const ZOOM_MIN = 0.5;
const ZOOM_MAX = 3;
const ZOOM_STEP = 0.25;

function clampZoom(value: number): number {
  const rounded = Math.round(value * 100) / 100;
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, rounded));
}

export function useInvoiceFilePreview(invoiceId: number | null, enabled: boolean) {
  const [preview, setPreview] = useState<InvoiceFilePreviewResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSeq = useRef(0);

  const clear = useCallback(() => {
    requestSeq.current += 1;
    setPreview((prev) => {
      if (prev?.url) URL.revokeObjectURL(prev.url);
      return null;
    });
    setError(null);
    setLoading(false);
  }, []);

  const load = useCallback(async () => {
    if (!invoiceId || !enabled) return;
    const seq = ++requestSeq.current;
    setLoading(true);
    setError(null);
    try {
      const next = await api.previewInvoiceFile(invoiceId);
      if (seq !== requestSeq.current) {
        URL.revokeObjectURL(next.url);
        return;
      }
      setPreview((prev) => {
        if (prev?.url) URL.revokeObjectURL(prev.url);
        return next;
      });
    } catch (err) {
      if (seq !== requestSeq.current) return;
      setPreview((prev) => {
        if (prev?.url) URL.revokeObjectURL(prev.url);
        return null;
      });
      setError(err instanceof Error ? err.message : "Could not load document");
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [invoiceId, enabled]);

  useEffect(() => {
    if (!enabled) {
      clear();
      return;
    }
    void load();
  }, [enabled, load, clear]);

  useEffect(() => () => clear(), [clear]);

  return { preview, loading, error, reload: load };
}

type InvoiceDocumentViewerProps = {
  invoiceId: number;
  className?: string;
  testId?: string;
};

export function InvoiceDocumentViewer({
  invoiceId,
  className,
  testId = "invoice-document-viewer",
}: InvoiceDocumentViewerProps) {
  const { preview, loading, error, reload } = useInvoiceFilePreview(invoiceId, true);
  const [zoom, setZoom] = useState(1);
  const bodyRef = useRef<HTMLDivElement>(null);

  const isPdf = preview?.mimeType === "application/pdf";
  const isImage = preview?.mimeType?.startsWith("image/") ?? false;
  const canZoom = Boolean(preview && (isPdf || isImage) && !loading && !error);

  useEffect(() => {
    setZoom(1);
  }, [invoiceId]);

  const zoomIn = useCallback(() => setZoom((z) => clampZoom(z + ZOOM_STEP)), []);
  const zoomOut = useCallback(() => setZoom((z) => clampZoom(z - ZOOM_STEP)), []);
  const zoomReset = useCallback(() => setZoom(1), []);

  // Ctrl/Cmd + scroll zooms the document only (not the browser page).
  useEffect(() => {
    const el = bodyRef.current;
    if (!el || !canZoom) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const direction = e.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP;
      setZoom((z) => clampZoom(z + direction));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [canZoom]);

  const zoomPercent = `${Math.round(zoom * 100)}%`;

  return (
    <div className={cn("invoice-document-viewer", className)} data-testid={testId}>
      <div className="invoice-document-toolbar">
        <div className="flex items-center gap-2 min-w-0 text-xs text-muted-foreground">
          <FileText className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{preview?.filename ?? "Original document"}</span>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {canZoom ? (
            <div
              className="flex items-center gap-0.5 mr-1"
              data-testid="invoice-document-zoom-controls"
            >
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0"
                aria-label="Zoom out"
                data-testid="button-document-zoom-out"
                disabled={zoom <= ZOOM_MIN}
                onClick={zoomOut}
              >
                <Minus className="h-3.5 w-3.5" />
              </Button>
              <button
                type="button"
                className="h-7 min-w-[3rem] px-1 text-xs tnum text-muted-foreground hover:text-foreground"
                aria-label="Reset zoom"
                data-testid="button-document-zoom-reset"
                onClick={zoomReset}
                title="Reset zoom (100%)"
              >
                {zoomPercent}
              </button>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 w-7 p-0"
                aria-label="Zoom in"
                data-testid="button-document-zoom-in"
                disabled={zoom >= ZOOM_MAX}
                onClick={zoomIn}
              >
                <Plus className="h-3.5 w-3.5" />
              </Button>
              {zoom !== 1 ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 w-7 p-0"
                  aria-label="Fit document"
                  data-testid="button-document-zoom-fit"
                  onClick={zoomReset}
                  title="Fit to view"
                >
                  <RotateCcw className="h-3.5 w-3.5" />
                </Button>
              ) : null}
            </div>
          ) : null}
          {preview && (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 px-2 text-xs shrink-0"
              data-testid="button-download-document"
              onClick={() => void api.downloadInvoiceFile(invoiceId)}
            >
              <Download className="h-3.5 w-3.5 mr-1" />
              Download
            </Button>
          )}
        </div>
      </div>

      <div
        ref={bodyRef}
        className={cn(
          "invoice-document-body",
          canZoom && "invoice-document-body--zoomable"
        )}
      >
        {loading && (
          <div className="invoice-document-placeholder">
            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            <span className="text-sm text-muted-foreground">Loading document…</span>
          </div>
        )}

        {!loading && error && (
          <div className="invoice-document-placeholder">
            <p className="text-sm text-destructive text-center px-4">{error}</p>
            <Button type="button" variant="outline" size="sm" onClick={() => void reload()}>
              Retry
            </Button>
          </div>
        )}

        {!loading && !error && preview && (isPdf || isImage) && (
          <div
            className="invoice-document-zoom-canvas"
            style={{
              width: `${zoom * 100}%`,
              height: `${zoom * 100}%`,
              minWidth: "100%",
              minHeight: "100%",
            }}
          >
            {isPdf ? (
              <iframe
                title="Invoice document"
                src={preview.url}
                className="invoice-document-frame"
                data-testid="iframe-invoice-pdf"
              />
            ) : (
              <img
                src={preview.url}
                alt="Invoice attachment"
                className="invoice-document-image"
                data-testid="img-invoice-preview"
                draggable={false}
              />
            )}
          </div>
        )}

        {!loading && !error && preview && !isPdf && !isImage && (
          <div className="invoice-document-placeholder">
            <p className="text-sm text-muted-foreground text-center px-4">
              Inline preview is not available for this file type.
            </p>
            <Button
              type="button"
              size="sm"
              onClick={() => void api.downloadInvoiceFile(invoiceId)}
            >
              <Download className="h-4 w-4 mr-1.5" />
              Download file
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

export type PreviewPaneMode = "summary" | "original";

export function InvoicePreviewModeToggle({
  mode,
  onChange,
  hasOriginal,
}: {
  mode: PreviewPaneMode;
  onChange: (mode: PreviewPaneMode) => void;
  hasOriginal: boolean;
}) {
  if (!hasOriginal) return null;

  return (
    <PageTabs
      className="mb-3 w-full"
      value={mode}
      onChange={(v) => onChange(v as PreviewPaneMode)}
      data-testid="invoice-preview-mode-tabs"
      tabs={[
        { value: "summary", label: "Extracted", testid: "tab-preview-summary" },
        { value: "original", label: "Original document", testid: "tab-preview-original" },
      ]}
    />
  );
}
