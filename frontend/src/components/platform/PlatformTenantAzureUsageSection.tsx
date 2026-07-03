import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { api } from "@/api/client";
import type { CreditLedgerEntry } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/cn";
import {
  formatOperationLabel,
  formatProviderLabel,
  ledgerAzureEntries,
  parseAzureCostBreakdown,
  sumAzureCostUsd,
  type AzureCostLineItem,
} from "@/lib/azureCostBreakdown";

function usd(value: number, digits = 6): string {
  return `$${value.toFixed(digits)}`;
}

function tokens(value: number | undefined): string {
  if (value == null) return "—";
  return value.toLocaleString();
}

function RateCard({ rates }: { rates: Record<string, number> }) {
  const entries = [
    ["DI prebuilt / 1k pages", rates.di_prebuilt_per_1000_pages_usd],
    ["DI read / 1k pages", rates.di_read_per_1000_pages_usd],
    ["Foundry input / 1M tokens", rates.foundry_input_per_1m_tokens_usd],
    ["Foundry output / 1M tokens", rates.foundry_output_per_1m_tokens_usd],
    ["OpenAI mini input / 1M tokens", rates.openai_mini_input_per_1m_tokens_usd],
    ["OpenAI mini output / 1M tokens", rates.openai_mini_output_per_1m_tokens_usd],
  ].filter(([, v]) => v != null);

  if (entries.length === 0) return null;

  return (
    <div className="rounded-md border border-border bg-muted/30 p-3 text-xs">
      <p className="font-medium mb-2">Rate card used for this document (USD)</p>
      <dl className="grid sm:grid-cols-2 gap-x-4 gap-y-1">
        {entries.map(([label, value]) => (
          <div key={label} className="flex justify-between gap-2">
            <dt className="text-muted-foreground">{label}</dt>
            <dd className="tnum font-medium">{usd(value as number, 4)}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function LineItemsTable({ items }: { items: AzureCostLineItem[] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-border bg-muted/40 text-left">
            <th className="px-3 py-2 font-medium">Service</th>
            <th className="px-3 py-2 font-medium">Model</th>
            <th className="px-3 py-2 font-medium">Operation</th>
            <th className="px-3 py-2 font-medium text-right">Pages</th>
            <th className="px-3 py-2 font-medium text-right">Input tokens</th>
            <th className="px-3 py-2 font-medium text-right">Output tokens</th>
            <th className="px-3 py-2 font-medium">Rate</th>
            <th className="px-3 py-2 font-medium text-right">Cost (USD)</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr key={`${item.operation}-${idx}`} className="border-b border-border last:border-0">
              <td className="px-3 py-2">{item.service}</td>
              <td className="px-3 py-2 font-mono">{item.model}</td>
              <td className="px-3 py-2 capitalize">{formatOperationLabel(item.operation)}</td>
              <td className="px-3 py-2 text-right tnum">{item.pages ?? "—"}</td>
              <td className="px-3 py-2 text-right tnum">{tokens(item.input_tokens)}</td>
              <td className="px-3 py-2 text-right tnum">{tokens(item.output_tokens)}</td>
              <td className="px-3 py-2 text-muted-foreground max-w-[12rem]">{item.rate_description}</td>
              <td className="px-3 py-2 text-right tnum font-medium">{usd(item.cost_usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function UsageRow({
  row,
  expanded,
  onToggle,
}: {
  row: CreditLedgerEntry;
  expanded: boolean;
  onToggle: () => void;
}) {
  const breakdown = parseAzureCostBreakdown(
    row.azure_cost_breakdown ?? undefined,
    row.azure_cost_usd ?? 0
  );

  return (
    <div className="border-b border-border last:border-0">
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-3 px-3 py-3 text-left text-sm hover:bg-muted/30 transition-colors"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <div className="min-w-0 flex-1 grid sm:grid-cols-[1fr_auto_auto_auto] gap-2 sm:gap-4 items-center">
          <div className="min-w-0">
            <p className="font-medium truncate">{row.filename ?? row.description}</p>
            <p className="text-xs text-muted-foreground">
              {row.created_at ? new Date(row.created_at).toLocaleString() : "—"}
              {row.invoice_id != null && <> · Invoice #{row.invoice_id}</>}
              {row.pages != null && <> · {row.pages} page{row.pages === 1 ? "" : "s"}</>}
            </p>
          </div>
          <span className="text-xs text-muted-foreground capitalize hidden sm:block">
            {breakdown ? formatProviderLabel(breakdown.provider) : "—"}
          </span>
          <span className="text-xs tnum text-muted-foreground hidden md:block">
            {breakdown?.inputTokensTotal != null || breakdown?.outputTokensTotal != null ? (
              <>
                {tokens(breakdown?.inputTokensTotal)} in / {tokens(breakdown?.outputTokensTotal)} out
              </>
            ) : (
              "—"
            )}
          </span>
          <span className="text-sm font-semibold tnum">{usd(row.azure_cost_usd ?? 0)}</span>
        </div>
      </button>

      {expanded && breakdown && (
        <div className="px-3 pb-4 pl-10 space-y-3">
          <div className="grid sm:grid-cols-4 gap-3 text-xs">
            <div>
              <p className="text-muted-foreground">Credits charged</p>
              <p className="font-medium tnum">{Math.abs(row.credits_delta).toLocaleString()}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Credits / page</p>
              <p className="font-medium tnum">{row.credits_per_page ?? "—"}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Pipeline provider</p>
              <p className="font-medium">{formatProviderLabel(breakdown.provider)}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Estimated Azure total</p>
              <p className="font-medium tnum">{usd(breakdown.totalUsd)}</p>
            </div>
          </div>
          {breakdown.rates && <RateCard rates={breakdown.rates} />}
          <LineItemsTable items={breakdown.lineItems} />
        </div>
      )}
    </div>
  );
}

export function PlatformTenantAzureUsageSection({ tenantId }: { tenantId: string }) {
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<CreditLedgerEntry[]>([]);
  const [pages, setPages] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<number | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .getPlatformTenantUsage(tenantId, page, 50)
      .then((data) => {
        setItems(data.items);
        setPages(data.pages);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load usage"))
      .finally(() => setLoading(false));
  }, [tenantId, page]);

  useEffect(() => {
    load();
  }, [load]);

  const azureRows = useMemo(() => ledgerAzureEntries(items), [items]);
  const pageAzureTotal = useMemo(() => sumAzureCostUsd(azureRows), [azureRows]);

  const serviceTotals = useMemo(() => {
    const totals = new Map<string, number>();
    for (const row of azureRows) {
      const breakdown = parseAzureCostBreakdown(
        row.azure_cost_breakdown ?? undefined,
        row.azure_cost_usd ?? 0
      );
      if (!breakdown) continue;
      for (const item of breakdown.lineItems) {
        totals.set(item.service, (totals.get(item.service) ?? 0) + item.cost_usd);
      }
    }
    return [...totals.entries()].sort((a, b) => b[1] - a[1]);
  }, [azureRows]);

  return (
    <Card className="p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">Azure cost breakdown</h2>
          <p className="text-xs text-muted-foreground mt-1">
            Per-document estimated Azure spend: Document Intelligence page charges, model input/output
            tokens, and applied USD rates.
          </p>
        </div>
        <p className="text-sm">
          Page total: <span className="font-semibold tnum">{usd(pageAzureTotal)}</span>
        </p>
      </div>

      {serviceTotals.length > 0 && (
        <dl className="grid sm:grid-cols-3 gap-3 text-sm">
          {serviceTotals.map(([service, total]) => (
            <div key={service} className="rounded-md border border-border px-3 py-2">
              <dt className="text-xs text-muted-foreground">{service}</dt>
              <dd className="text-lg font-semibold tnum">{usd(total)}</dd>
            </div>
          ))}
        </dl>
      )}

      {loading && <p className="text-sm text-muted-foreground">Loading usage history…</p>}
      {error && <p className="text-sm text-destructive">{error}</p>}

      {!loading && !error && azureRows.length === 0 && (
        <p className="text-sm text-muted-foreground">No document Azure costs recorded yet.</p>
      )}

      {!loading && !error && azureRows.length > 0 && (
        <div className={cn("rounded-md border border-border overflow-hidden")}>
          {azureRows.map((row) => (
            <UsageRow
              key={row.id}
              row={row}
              expanded={expandedId === row.id}
              onToggle={() => setExpandedId((id) => (id === row.id ? null : row.id))}
            />
          ))}
        </div>
      )}

      {pages > 1 && (
        <div className="flex items-center justify-between">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            Previous
          </Button>
          <span className="text-xs text-muted-foreground">
            Page {page} of {pages}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page >= pages || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </Button>
        </div>
      )}
    </Card>
  );
}
