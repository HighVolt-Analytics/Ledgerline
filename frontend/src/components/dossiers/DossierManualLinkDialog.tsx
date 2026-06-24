import { useEffect, useState } from "react";
import { Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetchDossiersPage, type DossierSummaryWithInvoiceId } from "@/lib/dossierApi";

type DossierManualLinkDialogProps = {
  open: boolean;
  slotLabel?: string | null;
  anchorDossierId: string;
  anchorInvoiceId: number;
  onClose: () => void;
  onSelect: (linkedInvoiceId: number) => Promise<void>;
};

export function DossierManualLinkDialog({
  open,
  slotLabel,
  anchorDossierId,
  anchorInvoiceId,
  onClose,
  onSelect,
}: DossierManualLinkDialogProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<DossierSummaryWithInvoiceId[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submittingId, setSubmittingId] = useState<number | null>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setResults([]);
    setError(null);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setResults([]);
      return;
    }

    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLoading(true);
      setError(null);
      fetchDossiersPage({ page: 1, pageSize: 20, q: trimmed, fresh: true })
        .then((page) => {
          if (cancelled) return;
          setResults(page.rows.filter((row) => row.id !== anchorDossierId));
        })
        .catch((err) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : "Search failed");
          }
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 250);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [open, query, anchorDossierId]);

  if (!open) return null;

  async function pick(row: DossierSummaryWithInvoiceId) {
    if (row.invoiceId === anchorInvoiceId) return;
    setSubmittingId(row.invoiceId);
    setError(null);
    try {
      await onSelect(row.invoiceId);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create link");
    } finally {
      setSubmittingId(null);
    }
  }

  return (
    <div className="dossier-manual-link-dialog__backdrop" role="presentation" onClick={onClose}>
      <div
        className="dossier-manual-link-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="dossier-manual-link-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="dossier-manual-link-dialog__head">
          <div>
            <h2 id="dossier-manual-link-title" className="dossier-manual-link-dialog__title">
              Link document
            </h2>
            {slotLabel ? (
              <p className="dossier-manual-link-dialog__subtitle">
                For slot: {slotLabel} — display only, does not affect validation.
              </p>
            ) : (
              <p className="dossier-manual-link-dialog__subtitle">
                Search by ref, vendor, PO, or document type. Display only.
              </p>
            )}
          </div>
          <button
            type="button"
            className="dossier-manual-link-dialog__close"
            aria-label="Close"
            onClick={onClose}
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="dossier-manual-link-dialog__search">
          <Search className="h-4 w-4 text-muted-foreground shrink-0" aria-hidden />
          <Input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search DOC-42, vendor, invoice no…"
            className="border-0 shadow-none focus-visible:ring-0"
          />
        </div>

        {error ? <p className="dossier-manual-link-dialog__error">{error}</p> : null}

        <div className="dossier-manual-link-dialog__results">
          {query.trim().length < 2 ? (
            <p className="text-xs text-muted-foreground px-1">Type at least 2 characters to search.</p>
          ) : loading ? (
            <p className="text-xs text-muted-foreground px-1">Searching…</p>
          ) : results.length === 0 ? (
            <p className="text-xs text-muted-foreground px-1">No documents found.</p>
          ) : (
            results.map((row) => (
              <button
                key={row.id}
                type="button"
                className="dossier-manual-link-dialog__result"
                disabled={row.invoiceId === anchorInvoiceId || submittingId != null}
                onClick={() => pick(row)}
              >
                  <span className="dossier-manual-link-dialog__result-ref tnum">{row.id}</span>
                  <span className="dossier-manual-link-dialog__result-main">
                    <span className="dossier-manual-link-dialog__result-vendor">{row.vendor}</span>
                    <span className="dossier-manual-link-dialog__result-meta">
                      {row.documentTypeCode} · {row.invoiceRef}
                    </span>
                  </span>
                </button>
            ))
          )}
        </div>

        <div className="dossier-manual-link-dialog__foot">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
        </div>
      </div>
    </div>
  );
}
