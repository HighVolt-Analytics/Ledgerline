import { FolderKanban, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/api/client";
import { DossierCard } from "@/components/dossiers/DossierCard";
import { ListSearchInput } from "@/components/ListSearchInput";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { TableSkeleton } from "@/components/skeleton/PageSkeletons";
import { Select } from "@/components/ui/select";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useResetOnTenantChange } from "@/hooks/useResetOnTenantChange";
import { fetchDossiersPage } from "@/lib/dossierApi";
import type { DossierSummary } from "@/lib/dossiers";
import {
  captureTenantFetchScope,
  handleTenantScopedLoadFailure,
  isTenantFetchScopeCurrent,
} from "@/lib/tenantSession";

const PAGE_SIZE = 12;

export function DossiersPage() {
  const [query, setQuery] = useState("");
  const search = useDebouncedValue(query.trim());
  const [typeFilter, setTypeFilter] = useState("all");
  const [page, setPage] = useState(1);
  const [rows, setRows] = useState<DossierSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [totalPages, setTotalPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [typeOptions, setTypeOptions] = useState<Array<{ value: string; label: string }>>([
    { value: "all", label: "All document types" },
  ]);
  const loadSeq = useRef(0);

  useResetOnTenantChange(() => {
    loadSeq.current += 1;
    setRows([]);
    setTotal(0);
    setTotalPages(1);
    setPage(1);
    setError(null);
    setLoading(true);
    setQuery("");
    setTypeFilter("all");
  });

  useEffect(() => {
    let cancelled = false;
    const scope = captureTenantFetchScope();
    api
      .getRuleBookConfig()
      .then((config) => {
        if (cancelled || !isTenantFetchScopeCurrent(scope)) return;
        const types = (config.document_types ?? [])
          .map((row) => ({
            value: row.code,
            label: `${row.code} · ${row.title || row.short_title || row.code}`,
          }))
          .sort((a, b) => a.value.localeCompare(b.value));
        setTypeOptions([{ value: "all", label: "All document types" }, ...types]);
      })
      .catch(() => {
        /* keep default */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const load = useCallback(
    async (options?: { silent?: boolean; fresh?: boolean }) => {
      const scope = captureTenantFetchScope();
      const seq = ++loadSeq.current;
      if (!options?.silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const res = await fetchDossiersPage({
          page,
          pageSize: PAGE_SIZE,
          documentTypeCode: typeFilter,
          q: search,
          fresh: options?.fresh,
        });
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        setRows(res.rows);
        setTotal(res.total);
        setTotalPages(Math.max(1, res.pages));
      } catch (err) {
        if (seq !== loadSeq.current || !isTenantFetchScopeCurrent(scope)) return;
        if (
          handleTenantScopedLoadFailure(err, {
            retry: () => {
              void load({ silent: true, fresh: true });
            },
          })
        ) {
          return;
        }
        setError(err instanceof Error ? err.message : "Failed to load processing queue");
      } finally {
        if (seq === loadSeq.current && isTenantFetchScopeCurrent(scope) && !options?.silent) {
          setLoading(false);
        }
      }
    },
    [page, search, typeFilter]
  );

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    setPage(1);
  }, [search, typeFilter]);

  const emptyMessage = useMemo(() => {
    if (loading) return null;
    if (search || typeFilter !== "all") return "No documents match your filters.";
    return "No documents yet. Uploaded and ingested items appear here after processing.";
  }, [loading, search, typeFilter]);

  return (
    <div data-testid="page-dossiers">
      <PageHeader
        title="Processing"
        subtitle="Latest posting bundles — invoice, supporting documents, full pipeline, and posting outcome."
        actions={
          <Button
            variant="surface"
            size="sm"
            className="h-8 gap-1.5 text-xs"
            onClick={() => void load({ fresh: true })}
            disabled={loading}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </Button>
        }
      />

      <Card className="overflow-hidden dossier-list-shell">
        <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-border flex-wrap">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <FolderKanban className="h-4 w-4 text-primary" />
            Recent documents
            <span className="text-muted-foreground tnum font-normal">({total})</span>
          </h3>
          <div className="flex items-center gap-2 ml-auto flex-wrap">
            <ListSearchInput
              value={query}
              onChange={setQuery}
              placeholder="Search documents…"
              testId="input-dossier-search"
            />
            <Select
              value={typeFilter}
              onValueChange={setTypeFilter}
              data-testid="filter-dossier-dt"
              className="w-[220px] h-8 text-xs"
              options={typeOptions}
            />
          </div>
        </div>

        {error ? (
          <div className="px-4 py-10 text-center text-sm text-destructive">{error}</div>
        ) : loading && rows.length === 0 ? (
          <TableSkeleton rows={8} columns={5} className="border-0 shadow-none" />
        ) : rows.length === 0 ? (
          <div className="px-4 py-10 text-center text-sm text-muted-foreground">{emptyMessage}</div>
        ) : (
          <div className="p-4">
            <div className="dossier-grid">
              {rows.map((dossier) => (
                <DossierCard key={dossier.id} dossier={dossier} />
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 px-4 py-3 border-t border-border">
          <p className="text-xs text-muted-foreground">
            Page {page} of {totalPages}
            <span className="hidden sm:inline"> · {total} dossier{total === 1 ? "" : "s"}</span>
          </p>
          <div className="flex items-center gap-1.5">
            <Button
              variant="outline"
              size="sm"
              className="h-8 px-2 text-xs"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1 || loading}
            >
              Prev
            </Button>
            {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
              <Button
                key={p}
                variant={p === page ? "default" : "outline"}
                size="sm"
                className="h-8 min-w-8 px-2 text-xs tnum"
                onClick={() => setPage(p)}
                disabled={loading}
              >
                {p}
              </Button>
            ))}
            <Button
              variant="outline"
              size="sm"
              className="h-8 px-2 text-xs"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages || loading}
            >
              Next
            </Button>
          </div>
        </div>
      </Card>
    </div>
  );
}
