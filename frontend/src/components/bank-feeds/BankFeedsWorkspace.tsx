import { useEffect, useMemo, useState } from "react";
import { Landmark, Play, Plus, Tags, Undo2 } from "lucide-react";
import { Link } from "react-router-dom";
import type { BankFeedQueueTab, BankTransaction } from "@/api/types";
import { BankFeedImportSection } from "@/components/bank-feeds/BankFeedImportSection";
import { BankFeedArchiveStatementCard } from "@/components/bank-feeds/BankFeedStatementCard";
import { BankFeedReconcileRow } from "@/components/bank-feeds/BankFeedReconcileRow";
import { EmptyState } from "@/components/EmptyState";
import { PageTabPanel, PageTabs } from "@/components/PageTabs";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Select } from "@/components/ui/select";
import { TableSkeleton } from "@/components/skeleton/PageSkeletons";
import { CURRENCIES } from "@/data/orgSetup";
import {
  useBankAccounts,
  useBankFeedMutations,
  useBankTransaction,
  useBankTransactions,
  useUnsettledSettlements,
  BANK_FEEDS_PAGE_SIZE,
} from "@/hooks/useBankFeeds";
import { usePermissions } from "@/hooks/usePermissions";
import { ApiError } from "@/api/client";
import { BANK_FEEDS_TRANSFER_ENABLED } from "@/lib/bankFeedFeatures";
import {
  formatMatchEntityLabel,
  formatMatchMethodLabel,
} from "@/lib/bankFeedCopy";
import { money } from "@/lib/format";

const TABS: { value: BankFeedQueueTab; label: string; testid: string }[] = [
  { value: "reconcile", label: "Reconcile", testid: "tab-bf-reconcile" },
  { value: "unsettled", label: "Unsettled", testid: "tab-bf-unsettled" },
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
  initialTab = null,
}: {
  initialAccountId?: number | null;
  initialTab?: BankFeedQueueTab | null;
}) {
  const { permissions } = usePermissions();
  const canPost = permissions?.permissions.Post === true;

  const accountsQ = useBankAccounts();
  const accounts = accountsQ.data ?? [];
  const [accountId, setAccountId] = useState<number | null>(initialAccountId);
  const [tab, setTab] = useState<BankFeedQueueTab>(initialTab ?? "reconcile");
  const [page, setPage] = useState(1);
  const [banner, setBanner] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [newAccountName, setNewAccountName] = useState("");
  const [newAccountCurrency, setNewAccountCurrency] = useState("AUD");

  const currencyOptions = useMemo(
    () =>
      CURRENCIES.map((c) => ({
        value: c.code,
        label: `${c.code} — ${c.name}`,
      })),
    []
  );

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

  useEffect(() => {
    if (initialTab) setTab(initialTab);
  }, [initialTab]);

  const txnsQ = useBankTransactions(
    accountId,
    tab === "unsettled" ? "reconcile" : tab,
    page,
    tab !== "unsettled"
  );
  const unsettledQ = useUnsettledSettlements(page, BANK_FEEDS_PAGE_SIZE, tab === "unsettled");
  const items = txnsQ.data?.data.items ?? [];
  const meta = tab === "unsettled" ? unsettledQ.data?.meta : txnsQ.data?.meta;
  const unsettledItems = unsettledQ.data?.data.items ?? [];
  const unsettledGrace = unsettledQ.data?.data.grace_days ?? 7;

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

  const onCreateAccount = async () => {
    const name = newAccountName.trim();
    if (!name) {
      setError("Account name is required");
      return;
    }
    try {
      const row = await mutations.createAccount.mutateAsync({
        name,
        currency: newAccountCurrency,
      });
      setAccountId(row.id);
      setCreateOpen(false);
      setNewAccountName("");
      setNewAccountCurrency(accounts[0]?.currency || "AUD");
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
          Import bank statements (PDF or CSV) and reconcile lines here — match payments, post journals
          {BANK_FEEDS_TRANSFER_ENABLED ? ", or transfer between accounts" : ""}.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={!canPost || busy}
            onClick={() => {
              setError(null);
              setNewAccountCurrency(accounts[0]?.currency || "AUD");
              setCreateOpen((open) => !open);
            }}
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

      {createOpen && canPost ? (
        <form
          className="flex flex-wrap items-end gap-3 rounded-md border border-border bg-muted/20 p-3"
          onSubmit={(e) => {
            e.preventDefault();
            void onCreateAccount();
          }}
          data-testid="bf-create-account-form"
        >
          <label className="flex min-w-[12rem] flex-col gap-1 text-xs">
            <span className="font-medium text-muted-foreground">Account name</span>
            <input
              type="text"
              value={newAccountName}
              onChange={(e) => setNewAccountName(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-2 text-sm"
              placeholder="Operating account"
              data-testid="bf-create-account-name"
            />
          </label>
          <label className="flex min-w-[14rem] flex-col gap-1 text-xs">
            <span className="font-medium text-muted-foreground">Currency</span>
            <Select
              value={newAccountCurrency}
              onValueChange={setNewAccountCurrency}
              options={currencyOptions}
              searchable
              size="sm"
              className="w-full"
              data-testid="bf-create-account-currency"
            />
          </label>
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={busy || !newAccountName.trim()}>
              Create account
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() => setCreateOpen(false)}
            >
              Cancel
            </Button>
          </div>
        </form>
      ) : null}

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
        {tab === "unsettled" ? (
          unsettledQ.isLoading ? (
            <TableSkeleton rows={6} />
          ) : unsettledItems.length === 0 ? (
            <EmptyState
              title="No unsettled cash"
              hint={`Paid payments and received collections with no verified bank match after ${unsettledGrace} day(s) appear here.`}
            />
          ) : (
            <div className="overflow-x-auto rounded-sm border border-[#d8dee4] dark:border-border">
              <table className="w-full text-sm">
                <thead className="bg-muted/40 text-left text-xs text-muted-foreground">
                  <tr>
                    <th className="px-3 py-2 font-medium">Type</th>
                    <th className="px-3 py-2 font-medium">Party</th>
                    <th className="px-3 py-2 font-medium">Invoice</th>
                    <th className="px-3 py-2 font-medium text-right">Amount</th>
                    <th className="px-3 py-2 font-medium">Settled</th>
                    <th className="px-3 py-2 font-medium text-right">Days</th>
                    <th className="px-3 py-2 font-medium">Bank match</th>
                  </tr>
                </thead>
                <tbody>
                  {unsettledItems.map((row) => (
                    <tr
                      key={`${row.entity_type}-${row.entity_id}`}
                      className="border-t border-border/60"
                      data-testid={`bf-unsettled-${row.entity_type}-${row.entity_id}`}
                    >
                      <td className="px-3 py-2 capitalize">{row.entity_type}</td>
                      <td className="px-3 py-2">{row.party_name ?? "—"}</td>
                      <td className="px-3 py-2">
                        {row.invoice_no ? (
                          <Link
                            to={`/invoices/${row.invoice_id}`}
                            className="text-primary hover:underline"
                          >
                            {row.invoice_no}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {money(row.amount, row.currency)}
                      </td>
                      <td className="px-3 py-2 tabular-nums">{row.settled_date}</td>
                      <td className="px-3 py-2 text-right tabular-nums">
                        {row.days_since_settled}
                      </td>
                      <td className="px-3 py-2 text-xs text-muted-foreground">
                        {row.has_suggested_bank_match ? (
                          <span>Suggested only · {money(row.allocated_bank_amount, row.currency)} allocated</span>
                        ) : row.allocated_bank_amount > 0 ? (
                          <span>Partial · {money(row.allocated_bank_amount, row.currency)} of {row.gross_amount != null ? money(row.gross_amount, row.currency) : "—"}</span>
                        ) : (
                          "None"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        ) : accountsQ.isLoading || (accountId != null && txnsQ.isLoading) ? (
          <TableSkeleton rows={6} />
        ) : accountId == null ? (
          <EmptyState
            title="Create a bank account"
            hint="Use Account above, then import a CSV or PDF in Import statements."
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
