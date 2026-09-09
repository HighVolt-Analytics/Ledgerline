import { useEffect, useState } from "react";
import { Landmark, Play, Tags } from "lucide-react";
import { Link } from "react-router-dom";
import type { BankFeedQueueTab } from "@/api/types";
import { BankFeedImportSection } from "@/components/bank-feeds/BankFeedImportSection";
import { BankFeedReconcileRow } from "@/components/bank-feeds/BankFeedReconcileRow";
import { BankFeedStatementLinesTable } from "@/components/bank-feeds/BankFeedStatementLinesTable";
import { EmptyState } from "@/components/EmptyState";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TableSkeleton } from "@/components/skeleton/PageSkeletons";
import {
  useBankAccounts,
  useBankFeedImports,
  useBankFeedMutations,
  useBankTransactions,
  BANK_FEEDS_PAGE_SIZE,
} from "@/hooks/useBankFeeds";
import { usePermissions } from "@/hooks/usePermissions";
import { ApiError } from "@/api/client";
import { BANK_FEEDS_TRANSFER_ENABLED } from "@/lib/bankFeedFeatures";

const TAB_DEFS: { value: BankFeedQueueTab; label: string; testid: string }[] = [
  { value: "pending", label: "Reconciliation Pending", testid: "tab-bf-pending" },
  { value: "reconciled", label: "Reconciled", testid: "tab-bf-reconciled" },
  { value: "statement", label: "Bank Statement", testid: "tab-bf-statement" },
];

function formatImportedAt(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function BankFeedsWorkspace({
  initialAccountId = null,
  initialTab = null,
}: {
  initialAccountId?: number | null;
  initialTab?: BankFeedQueueTab | null;
}) {
  const { permissions } = usePermissions();
  const canPost = permissions?.permissions.Approve === true;

  const accountsQ = useBankAccounts();
  const accounts = accountsQ.data ?? [];
  const [accountId, setAccountId] = useState<number | null>(initialAccountId);
  const [tab, setTab] = useState<BankFeedQueueTab>(initialTab ?? "pending");
  const [page, setPage] = useState(1);
  const [importsPage, setImportsPage] = useState(1);
  const [banner, setBanner] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reverseId, setReverseId] = useState<number | null>(null);

  const mutations = useBankFeedMutations();

  useEffect(() => {
    if (initialAccountId != null) {
      setAccountId(initialAccountId);
      return;
    }
    if (accountId == null && accounts.length > 0) {
      setAccountId(accounts[0]!.id);
    }
  }, [accounts, accountId, initialAccountId]);

  useEffect(() => {
    setPage(1);
    setImportsPage(1);
  }, [accountId, tab]);

  useEffect(() => {
    if (initialTab) setTab(initialTab);
  }, [initialTab]);

  const txnsQ = useBankTransactions(accountId, tab, page, true);
  const pendingCountQ = useBankTransactions(
    accountId,
    "pending",
    1,
    accountId != null && tab !== "pending"
  );
  const importsQ = useBankFeedImports(
    accountId,
    importsPage,
    BANK_FEEDS_PAGE_SIZE,
    tab === "statement"
  );
  const items = txnsQ.data?.data.items ?? [];
  const meta = txnsQ.data?.meta;
  const pendingTotal =
    tab === "pending"
      ? (meta?.total ?? null)
      : (pendingCountQ.data?.meta?.total ?? null);
  const tabs = TAB_DEFS.map((t) =>
    t.value === "pending" && pendingTotal != null && pendingTotal > 0
      ? { ...t, label: `Reconciliation Pending (${pendingTotal})` }
      : t
  );
  const imports = importsQ.data?.data.items ?? [];
  const importsMeta = importsQ.data?.meta;

  const busy =
    mutations.runMatch.isPending ||
    mutations.runCategorize.isPending ||
    mutations.confirmMatch.isPending ||
    mutations.unmatch.isPending ||
    mutations.exclude.isPending ||
    mutations.createMatch.isPending ||
    mutations.createJournal.isPending ||
    mutations.transfer.isPending ||
    mutations.createNote.isPending ||
    mutations.reverseCreate.isPending ||
    mutations.importStatement.isPending;

  const flash = (msg: string) => {
    setBanner(msg);
    setError(null);
  };

  const fail = (err: unknown) => {
    const msg =
      err instanceof ApiError
        ? err.message
        : err instanceof Error
          ? err.message
          : "Request failed";
    setError(msg);
  };

  const onRunMatch = async () => {
    if (accountId == null) return;
    try {
      const result = await mutations.runMatch.mutateAsync(accountId);
      const auto = result.items.filter((i) => i.auto_matched).length;
      const written = result.items.reduce((n, i) => n + i.matches_written, 0);
      flash(
        `Match run complete — ${written} link(s) written` +
          (auto ? ` · ${auto} automatic` : "")
      );
    } catch (err) {
      fail(err);
    }
  };

  const onRunCategorize = async () => {
    if (accountId == null) return;
    try {
      const result = await mutations.runCategorize.mutateAsync(accountId);
      flash(
        `Categorize run complete — ${result.categorized_count} unmatched line(s) categorized`
      );
    } catch (err) {
      fail(err);
    }
  };

  const onConfirmReverse = async () => {
    if (reverseId == null) return;
    try {
      await mutations.reverseCreate.mutateAsync(reverseId);
      flash("Journal reversed — line returned to Reconciliation Pending");
      setReverseId(null);
    } catch (err) {
      fail(err);
    }
  };

  const emptyHint =
    tab === "pending"
      ? "Import a statement, then match or categorize lines here."
      : tab === "reconciled"
        ? "Matched and posted bank lines appear here after you reconcile them."
        : "Upload a statement to see its lines and import history.";

  return (
    <div className="space-y-6" data-testid="bank-feeds-workspace">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground max-w-2xl">
          Import bank statements (PDF or CSV) and reconcile lines here — match payments, post
          journals
          {BANK_FEEDS_TRANSFER_ENABLED ? ", or transfer between accounts" : ""}.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            disabled={!canPost || busy || accountId == null}
            onClick={() => void onRunMatch()}
            data-testid="bf-run-match"
          >
            <Play className="h-4 w-4 mr-1" /> Run match
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!canPost || busy || accountId == null}
            onClick={() => void onRunCategorize()}
            data-testid="bf-run-categorize"
          >
            <Tags className="h-4 w-4 mr-1" /> Run categorize
          </Button>
        </div>
      </div>

      {(banner || error) && (
        <p
          className={
            error ? "text-sm text-destructive" : "text-sm text-muted-foreground"
          }
          role={error ? "alert" : undefined}
        >
          {error || banner}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Landmark className="h-4 w-4 text-muted-foreground" />
        <select
          className="h-9 min-w-[12rem] rounded-md border border-input bg-background px-2 text-sm"
          value={accountId ?? ""}
          onChange={(e) =>
            setAccountId(e.target.value ? Number(e.target.value) : null)
          }
          data-testid="bf-account-select"
        >
          {accounts.length === 0 && <option value="">No accounts yet</option>}
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name} ({a.currency}
              {a.account_mask ? ` · ${a.account_mask}` : ""})
            </option>
          ))}
        </select>
        <Link
          to="/creations?tab=banks&banksSection=list"
          className="text-xs text-muted-foreground underline hover:text-foreground"
          data-testid="bf-manage-accounts-link"
        >
          Manage accounts
        </Link>
        {!canPost && (
          <span className="text-xs text-muted-foreground">
            View only — Post privilege required to reconcile.
          </span>
        )}
      </div>

      <BankFeedImportSection
        accountId={accountId}
        canPost={canPost}
        onImportSuccess={(message) => {
          flash(message);
          setTab("pending");
        }}
      />

      <PageTabs
        tabs={tabs}
        value={tab}
        onChange={(v) => setTab(v as BankFeedQueueTab)}
        data-testid="bf-tabs"
      />

      <PageTabPanel value={tab} active={tab} className="space-y-4">
        {accountsQ.isLoading || (accountId != null && txnsQ.isLoading) ? (
          <TableSkeleton rows={6} />
        ) : accountId == null ? (
          <EmptyState
            title="No bank account selected"
            hint="Add or manage accounts in Contacts → Banks, then import a statement here."
            action={
              <Link
                to="/creations?tab=banks&banksSection=list"
                className="text-sm underline"
                data-testid="bf-manage-banks-link"
              >
                Open Contacts → Banks
              </Link>
            }
          />
        ) : tab === "statement" ? (
          <>
            <div className="space-y-2" data-testid="bf-uploaded-statements">
              <div className="flex items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold">Uploaded statements</h3>
                {importsMeta?.total != null ? (
                  <span className="text-xs text-muted-foreground">
                    {importsMeta.total} upload{importsMeta.total === 1 ? "" : "s"}
                  </span>
                ) : null}
              </div>
              {importsQ.isLoading ? (
                <TableSkeleton rows={3} />
              ) : imports.length === 0 ? (
                <p className="text-sm text-muted-foreground rounded-md border border-dashed border-border px-3 py-4">
                  No statements uploaded for this account yet.
                </p>
              ) : (
                <div className="overflow-x-auto rounded-sm border border-[#d8dee4] dark:border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 font-medium">File</th>
                        <th className="px-3 py-2 font-medium">Imported</th>
                        <th className="px-3 py-2 font-medium">Source</th>
                        <th className="px-3 py-2 font-medium text-right">Accepted</th>
                        <th className="px-3 py-2 font-medium text-right">Duplicates</th>
                        <th className="px-3 py-2 font-medium text-right">Errors</th>
                        <th className="px-3 py-2 font-medium">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {imports.map((imp) => (
                        <tr
                          key={imp.id}
                          className="border-t border-border/60"
                          data-testid={`bf-import-row-${imp.id}`}
                        >
                          <td className="px-3 py-2 font-medium">
                            {imp.filename || `Import #${imp.id}`}
                          </td>
                          <td className="px-3 py-2 text-muted-foreground whitespace-nowrap">
                            {formatImportedAt(imp.imported_at)}
                          </td>
                          <td className="px-3 py-2 capitalize text-muted-foreground">
                            {imp.source}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums">
                            {imp.accepted_count}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                            {imp.duplicate_count}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                            {imp.error_count}
                          </td>
                          <td className="px-3 py-2 capitalize">{imp.status}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {importsMeta && (importsMeta.pages ?? 1) > 1 ? (
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>
                    Uploads page {importsMeta.page} of {importsMeta.pages}
                  </span>
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={importsPage <= 1 || busy}
                      onClick={() => setImportsPage((p) => Math.max(1, p - 1))}
                    >
                      Previous
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={importsPage >= (importsMeta.pages ?? 1) || busy}
                      onClick={() => setImportsPage((p) => p + 1)}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              ) : null}
            </div>

            <div className="space-y-2">
              <h3 className="text-sm font-semibold">Statement lines</h3>
              {items.length === 0 ? (
                <EmptyState title="No statement lines" hint={emptyHint} />
              ) : (
                <BankFeedStatementLinesTable items={items} variant="statement" />
              )}
            </div>
          </>
        ) : items.length === 0 ? (
          <EmptyState
            title={
              tab === "pending"
                ? "Nothing pending reconciliation"
                : "No reconciled transactions"
            }
            hint={emptyHint}
          />
        ) : tab === "pending" ? (
          <div className="overflow-x-auto rounded-sm border border-[#d8dee4] dark:border-border">
            {items.map((txn) => (
              <BankFeedReconcileRow
                key={txn.id}
                summary={txn}
                accounts={accounts}
                canPost={canPost}
                busy={busy}
                onConfirm={async (matchId) => {
                  await mutations.confirmMatch.mutateAsync(matchId);
                  flash("Suggestion confirmed");
                }}
                onManualMatch={async (args) => {
                  await mutations.createMatch.mutateAsync(args);
                  flash("Manual match created");
                }}
                onCreateJournal={async (transactionId, body) => {
                  await mutations.createJournal.mutateAsync({ transactionId, body });
                  flash("Journal posted");
                }}
                onTransfer={async (args) => {
                  await mutations.transfer.mutateAsync(args);
                  flash("Transfer posted");
                }}
                onExclude={async (transactionId) => {
                  await mutations.exclude.mutateAsync({
                    transactionId,
                    reason: "Excluded",
                  });
                  flash("Transaction excluded");
                }}
                onPostNote={async (transactionId, body) => {
                  await mutations.createNote.mutateAsync({ transactionId, body });
                }}
              />
            ))}
          </div>
        ) : (
          <BankFeedStatementLinesTable
            items={items}
            variant="reconciled"
            canPost={canPost}
            busy={busy}
            onReverse={(id) => setReverseId(id)}
          />
        )}

        {tab !== "statement" && meta && (meta.pages ?? 1) > 1 ? (
          <div className="flex items-center justify-between px-1 py-2 text-xs text-muted-foreground">
            <span>
              Page {meta.page} of {meta.pages} · {meta.total} total
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={page <= 1 || busy}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={page >= (meta.pages ?? 1) || busy}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}

        {tab === "statement" && meta && (meta.pages ?? 1) > 1 ? (
          <div className="flex items-center justify-between px-1 py-2 text-xs text-muted-foreground">
            <span>
              Lines page {meta.page} of {meta.pages} · {meta.total} total
            </span>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                disabled={page <= 1 || busy}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                Previous
              </Button>
              <Button
                size="sm"
                variant="outline"
                disabled={page >= (meta.pages ?? 1) || busy}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </PageTabPanel>

      <ConfirmDialog
        open={reverseId != null}
        title="Reverse this entry?"
        description="A reversing journal will be posted as of today. The bank line returns to Reconciliation Pending."
        confirmLabel="Reverse this entry"
        destructive
        busy={mutations.reverseCreate.isPending}
        onCancel={() => setReverseId(null)}
        onConfirm={() => void onConfirmReverse()}
      />
    </div>
  );
}
