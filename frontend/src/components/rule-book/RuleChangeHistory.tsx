import { History } from "lucide-react";
import { api } from "@/api/client";
import type { RuleBookChangelogEntry } from "@/api/types";
import { Card } from "@/components/ui/card";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import { queryKeys } from "@/lib/queryClient";

function formatWhen(iso: string) {
  try {
    return new Date(iso).toLocaleString("en-AU", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function describeEntry(entry: RuleBookChangelogEntry) {
  const detail = entry.detail ?? {};
  const actor =
    (typeof detail.actor_name === "string" && detail.actor_name) ||
    (typeof detail.actor_email === "string" && detail.actor_email) ||
    "Unknown";

  if (entry.event === "rule_book_updated") {
    const changes = detail.changes as Record<string, unknown> | undefined;
    const sections = changes ? Object.keys(changes) : [];
    const sectionLabel =
      sections.length > 0 ? sections.join(", ").replaceAll("_", " ") : "configuration";
    return `${actor} updated ${sectionLabel}`;
  }

  if (entry.event === "invoices_remapped") {
    const updated =
      typeof detail.updated === "number" ? detail.updated : 0;
    const ids = Array.isArray(detail.invoice_ids) ? detail.invoice_ids : [];
    const idPreview = ids.slice(0, 5).join(", ");
    const suffix =
      ids.length > 5 ? ` (+${ids.length - 5} more)` : idPreview ? ` (${idPreview})` : "";
    return `${actor} re-mapped ${updated} document${updated === 1 ? "" : "s"}${suffix}`;
  }

  return `${actor} — ${entry.event}`;
}

export function RuleChangeHistory() {
  const CHANGELOG_LIMIT = 10;

  const { data = [], isLoading, isError, blocked } = useTenantQuery({
    queryKey: [...queryKeys.ruleBookChangelog(), CHANGELOG_LIMIT],
    queryFn: () => api.getRuleBookChangelog(CHANGELOG_LIMIT),
  });
  const showLoading = isLoading || blocked;

  return (
    <Card className="mt-5 overflow-hidden" data-testid="rulebook-changelog">
      <div className="px-4 py-3 border-b border-border flex items-center gap-2">
        <History className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-semibold">Rule change history</h3>
      </div>
      {showLoading ? (
        <div className="px-4 py-6 text-sm text-muted-foreground">Loading change history…</div>
      ) : isError ? (
        <div className="px-4 py-6 text-sm text-destructive">Could not load change history.</div>
      ) : data.length === 0 ? (
        <div className="px-4 py-6 text-sm text-muted-foreground">
          Saves and remaps are recorded here with actor, summary, and affected document IDs.
        </div>
      ) : (
        <ul className="divide-y divide-border/60">
          {data.map((entry) => (
            <li key={entry.id} className="px-4 py-3 text-sm">
              <div className="font-medium">{describeEntry(entry)}</div>
              <div className="text-xs text-muted-foreground mt-0.5">{formatWhen(entry.created_at)}</div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
