import { useEffect, useState } from "react";
import { Landmark, Play, Plus, Tags, Undo2 } from "lucide-react";
import type { BankFeedQueueTab, BankTransaction } from "@/api/types";
import { BankFeedImportSection } from "@/components/bank-feeds/BankFeedImportSection";
import { BankFeedArchiveStatementCard } from "@/components/bank-feeds/BankFeedStatementCard";
import { BankFeedReconcileRow } from "@/components/bank-feeds/BankFeedReconcileRow";
import { EmptyState } from "@/components/EmptyState";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { TableSkeleton } from "@/components/skeleton/PageSkeletons";
import {
  useBankAccounts,
  useBankFeedMutations,
  useBankTransaction,
  useBankTransactions,
} from "@/hooks/useBankFeeds";
import { usePermissions } from "@/hooks/usePermissions";
import { ApiError } from "@/api/client";
import {
  formatMatchEntityLabel,
  formatMatchMethodLabel,
} from "@/lib/bankFeedCopy";
import { money } from "@/lib/format";

const TABS: { value: BankFeedQueueTab; label: string; testid: string }[] = [
  { value: "reconcile", label: "Reconcile", testid: "tab-bf-reconcile" },
  { value: "matched", label: "Matched", testid: "tab-bf-matched" },
  { value: "posted", label: "Posted", testid: "tab-bf-posted" },
  { value: "excluded", label: "Excluded", testid: "tab-bf-excluded" },
];

function PostedArchiveRow({
  summary,
  canPost,
  busy,
  onReverse,
}: {
  summary: BankTransaction;
  canPost: boolean;
  busy: boolean;
  onReverse: (transactionId: number) => Promise<void>;
}) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const detailQ = useBankTransaction(summary.id, true);
  const txn = detailQ.data ?? summary;

  return (
    <>
      <BankFeedArchiveStatementCard
        txn={txn}
        summary={
          txn.posted_journal_batch_id ? (
            <span>
              Journal batch #{txn.posted_journal_batch_id}
              {txn.category_coa ? ` · ${txn.category_coa}` : ""}
            </span>
          ) : null
        }
        actions={
          canPost ? (
            <Button
              size="sm"
              variant="outline"
              className="border-destructive/40 text-destructive"
              disabled={busy}
              onClick={() => setConfirmOpen(true)}
              data-testid={`bf-reverse-${txn.id}`}
            >
              <Undo2 className="h-4 w-4 mr-1" /> Reverse this entry
            </Button>
          ) : null
        }
      />
      <ConfirmDialog
        open={confirmOpen}
        title="Reverse this entry?"
        description="A reversing journal will be posted as of today. The bank line returns to Unmatched."
        confirmLabel="Reverse this entry"
        destructive
        busy={busy}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={() => {
          setConfirmOpen(false);
          void onReverse(txn.id);
        }}
      />
    </>
  );
}

function MatchedArchiveRow({ summary }: { summary: BankTransaction }) {
  const detailQ = useBankTransaction(summary.id, true);
  const txn = detailQ.data ?? summary;
  const active = (txn.matches ?? []).filter((m) => m.unmatched_at == null);

  return (
    <BankFeedArchiveStatementCard
      txn={txn}
      summary={
        active.length > 0 ? (
          <ul className="space-y-1">
            {active.map((m) => (
              <li key={m.id}>
                {formatMatchEntityLabel(m)} · {formatMatchMethodLabel(m.match_method)} ·{" "}
                {money(m.allocated_amount, txn.currency)}
              </li>
            ))}
          </ul>
        ) : (
          "Matched"
        )
      }
    />
  );
}

export function BankFeedsWorkspace({
  initialAccountId = null,
}: {
  initialAccountId?: number | null;
}) {
  const { permissions } = usePermissions();
  const canPost = permissions?.permissions.Post === true;

  const accountsQ = useBankAccounts();
  const accounts = accountsQ.data ?? [];
  const [accountId, setAccountId] = useState<number | null>(initialAccountId);
  const [tab, setTab] = useState<BankFeedQueueTab>("reconcile");
  const [page, setPage] = useState(1);
  const [banner, setBanner] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
  }, [accountId, tab]);

  const txnsQ = useBankTransactions(accountId, tab, page);
  const items = txnsQ.data?.data.items ?? [];
  const meta = txnsQ.data?.meta;

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
    mutations.createAccount.isPending ||
    mutations.importCsv.isPending;

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

  const onCreateAccount = async () => {
    const name = window.prompt("Bank account name");
    if (!name?.trim()) return;
    const currency =
      window.prompt("Currency (3-letter)", accounts[0]?.currency || "AUD") || "AUD";
    try {
      const row = await mutations.createAccount.mutateAsync({
        name: name.trim(),
        currency: currency.trim().toUpperCase(),
      });
      setAccountId(row.id);
      flash(`Created account “${row.name}”`);
    } catch (err) {
      fail(err);
    }
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

  return (
    <div className="space-y-6" data-testid="bank-feeds-workspace">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-muted-foreground max-w-2xl">
          Import bank CSV statements and reconcile lines here — match payments, post journals, or
          transfer between accounts.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!canPost || busy}
            onClick={() => void onCreateAccount()}
            data-testid="bf-create-account"
          >
            <Plus className="h-4 w-4 mr-1" /> Account
          </Button>
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
          setTab("reconcile");
        }}
      />

      <PageTabs
        tabs={TABS}
        value={tab}
        onChange={(v) => setTab(v as BankFeedQueueTab)}
        data-testid="bf-tabs"
      />

      <PageTabPanel value={tab} active={tab}>
        {accountsQ.isLoading || (accountId != null && txnsQ.isLoading) ? (
          <TableSkeleton rows={6} />
        ) : accountId == null ? (
          <EmptyState
            title="Create a bank account"
            hint="Use Account above, then import a CSV in Import statements."
          />
        ) : items.length === 0 ? (
          <EmptyState
            title={`No ${tab} transactions`}
            hint={
              tab === "reconcile"
                ? "Import a statement or run match to populate the reconcile queue."
                : "Nothing in this archive yet."
            }
          />
        ) : tab === "reconcile" ? (
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
                  await mutations.exclude.mutateAsync({ transactionId, reason: "Excluded" });
                  flash("Transaction excluded");
                }}
                onPostNote={async (transactionId, body) => {
                  await mutations.createNote.mutateAsync({ transactionId, body });
                }}
              />
            ))}
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((txn) =>
              tab === "posted" ? (
                <PostedArchiveRow
                  key={txn.id}
                  summary={txn}
                  canPost={canPost}
                  busy={busy}
                  onReverse={async (transactionId) => {
                    await mutations.reverseCreate.mutateAsync(transactionId);
                    flash("Journal reversed");
                  }}
                />
              ) : tab === "matched" ? (
                <MatchedArchiveRow key={txn.id} summary={txn} />
              ) : (
                <BankFeedArchiveStatementCard
                  key={txn.id}
                  txn={txn}
                  summary="Excluded from reconcile"
                />
              )
            )}
          </div>
        )}
        {meta && (meta.pages ?? 1) > 1 && (
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
        )}
      </PageTabPanel>
    </div>
  );
}
