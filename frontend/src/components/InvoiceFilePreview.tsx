import { useCallback, useEffect, useRef, useState } from "react";
import { Download, FileText, Loader2 } from "lucide-react";
import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { PageTabs } from "@/components/PageTabs";
import { cn } from "@/lib/cn";

export type InvoiceFilePreviewResult = {
  url: string;
  mimeType: string;
  filename: string;
};

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

  const isPdf = preview?.mimeType === "application/pdf";
  const isImage = preview?.mimeType?.startsWith("image/") ?? false;

  return (
    <div className={cn("invoice-document-viewer", className)} data-testid={testId}>
      <div className="invoice-document-toolbar">
        <div className="flex items-center gap-2 min-w-0 text-xs text-muted-foreground">
          <FileText className="h-3.5 w-3.5 shrink-0" />
          <span className="truncate">{preview?.filename ?? "Original document"}</span>
        </div>
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

      <div className="invoice-document-body">
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

        {!loading && !error && preview && isPdf && (
          <iframe
            title="Invoice document"
            src={preview.url}
            className="invoice-document-frame"
            data-testid="iframe-invoice-pdf"
          />
        )}

        {!loading && !error && preview && isImage && (
          <img
            src={preview.url}
            alt="Invoice attachment"
            className="invoice-document-image"
            data-testid="img-invoice-preview"
          />
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
        { value: "summary", label: "Summary", testid: "tab-preview-summary" },
        { value: "original", label: "Original", testid: "tab-preview-original" },
      ]}
    />
  );
}
