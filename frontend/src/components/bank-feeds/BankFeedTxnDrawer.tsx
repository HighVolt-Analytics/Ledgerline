/**
 * Bank transaction review drawer.
 *
 * Shell: DetailDrawer (shared portal pattern used by ReconciliationDetailDrawer).
 * Actions: ClaimDetailPanel-style confirm/reject buttons gated by canPost.
 * Audit: DocumentAuditTrail-style collapsible trail.
 */
import { useEffect, useMemo, useState } from "react";
import { BookPlus, Check, Link2, Split, Ban, Undo2, X } from "lucide-react";
import type { BankTransaction, BankTransactionMatch } from "@/api/types";
import { api } from "@/api/client";
import { BankFeedTxnAuditTrail } from "@/components/bank-feeds/BankFeedTxnAuditTrail";
import { DetailDrawer } from "@/components/DetailDrawer";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Select } from "@/components/ui/select";
import {
  useBankMatchTargets,
  useBankTransaction,
  useBankTransactionAudit,
} from "@/hooks/useBankFeeds";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { useInstitutionSettings } from "@/hooks/useInstitutionSettings";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import {
  formatMatchEntityLabel,
  formatMatchMethodLabel,
  formatMatchReasonsPlain,
} from "@/lib/bankFeedCopy";
import { mergeCoaOptionsWithSavedValue } from "@/lib/coaAccountOptions";
import { money } from "@/lib/format";
import { queryKeys } from "@/lib/queryClient";
import { cn } from "@/lib/cn";

const NEW_PARTY = "__new__";

function activeMatches(txn: BankTransaction | undefined): BankTransactionMatch[] {
  return (txn?.matches ?? []).filter((m) => m.unmatched_at == null);
}

type PendingConfirm =
  | { kind: "reject"; matchId: number }
  | { kind: "unmatch"; matchId: number }
  | { kind: "exclude" }
  | { kind: "reverseCreate" }
  | null;

export function BankFeedTxnDrawer({
  transactionId,
  open,
  onClose,
  canPost,
  busy,
  onConfirm,
  onRejectSuggestion,
  onUnmatch,
  onExclude,
  onManualMatch,
  onSetCategory,
  onCreateJournal,
  onReverseCreate,
}: {
  transactionId: number | null;
  open: boolean;
  onClose: () => void;
  canPost: boolean;
  busy: boolean;
  onConfirm: (matchId: number) => Promise<void>;
  onRejectSuggestion: (matchId: number) => Promise<void>;
  onUnmatch: (matchId: number) => Promise<void>;
  onExclude: (transactionId: number, reason?: string) => Promise<void>;
  onManualMatch: (args: {
    transactionId: number;
    matched_type: "payment" | "collection";
    matched_id: number;
    allocated_amount?: number | null;
  }) => Promise<void>;
  onSetCategory: (args: {
    transactionId: number;
    category_coa: string | null;
  }) => Promise<void>;
  onCreateJournal: (
    transactionId: number,
    body: {
      party_type: "vendor" | "customer";
      party_id?: number | null;
      create_party?: { name: string } | null;
      ledger: string;
      description: string;
      tax_rate_percent: number;
    }
  ) => Promise<void>;
  onReverseCreate: (transactionId: number) => Promise<void>;
}) {
  const detailQ = useBankTransaction(transactionId, open && transactionId != null);
  const auditQ = useBankTransactionAudit(transactionId, open && transactionId != null);
  const txn = detailQ.data;
  const matches = activeMatches(txn);
  const unmatched = txn?.match_status === "unmatched";
  const posted = txn?.match_status === "posted";
  const { options: ledgerOptions, isLoading: coaLoading } = useCoaAccountOptions({
    includeEmpty: true,
    emptyLabel: "— No category —",
    enabled: open && unmatched,
  });
  const { options: createLedgerOptions, isLoading: createCoaLoading } = useCoaAccountOptions({
    includeEmpty: false,
    enabled: open && unmatched,
  });
  const settingsQ = useInstitutionSettings(open && unmatched);
  const statutoryRate = settingsQ.data?.statutory_tax_rate ?? null;
  const moneyIn = txn?.money_flow === "in";
  const vendorsQ = useTenantQuery({
    queryKey: queryKeys.vendors(),
    queryFn: () => api.listVendors({ fresh: true }),
    enabled: open && unmatched && !moneyIn,
  });
  const customersQ = useTenantQuery({
    queryKey: queryKeys.customers(),
    queryFn: () => api.listCustomers({ fresh: true }),
    enabled: open && unmatched && moneyIn,
  });

  const matchedType: "payment" | "collection" =
    txn?.money_flow === "in" ? "collection" : "payment";
  const targetsQ = useBankMatchTargets(
    matchedType,
    txn?.bank_account_id ?? null,
    open && txn != null && txn.match_status !== "excluded" && !posted
  );

  const [matchedId, setMatchedId] = useState("");
  const [allocAmount, setAllocAmount] = useState("");
  const [showSplit, setShowSplit] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<PendingConfirm>(null);
  const [categoryDraft, setCategoryDraft] = useState("");
  const [partyChoice, setPartyChoice] = useState("");
  const [newPartyName, setNewPartyName] = useState("");
  const [createLedger, setCreateLedger] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [taxRate, setTaxRate] = useState("0");

  useEffect(() => {
    setMatchedId("");
    setAllocAmount("");
    setShowSplit(false);
    setActionError(null);
    setPendingConfirm(null);
    setCategoryDraft(txn?.category_coa ?? "");
    setPartyChoice("");
    setNewPartyName("");
    setCreateLedger(txn?.category_coa ?? "");
    setCreateDescription(txn?.description ?? "");
    setTaxRate("0");
  }, [transactionId, matchedType, txn?.category_coa, txn?.description]);

  const targetOptions = useMemo(
    () =>
      (targetsQ.data ?? []).map((t) => ({
        value: String(t.id),
        label: t.display_label,
      })),
    [targetsQ.data]
  );

  const suggested = matches.filter((m) => m.match_method === "suggested");
  const confirmed = matches.filter((m) => m.match_method !== "suggested");

  const statusLabel =
    txn?.match_status === "suggested"
      ? "Needs review"
      : txn?.match_status
        ? txn.match_status.charAt(0).toUpperCase() + txn.match_status.slice(1)
        : undefined;

  const run = async (fn: () => Promise<void>) => {
    setActionError(null);
    try {
      await fn();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Action failed");
    }
  };

  const submitManual = async (partial: boolean) => {
    if (transactionId == null) return;
    const id = Number(matchedId);
    if (!Number.isFinite(id) || id < 1) {
      setActionError(
        matchedType === "collection"
          ? "Select a collection to link"
          : "Select a payment to link"
      );
      return;
    }
    let allocated: number | null | undefined;
    if (partial || allocAmount.trim()) {
      const n = Number(allocAmount);
      if (!Number.isFinite(n) || n <= 0) {
        setActionError("Enter a positive amount for the split");
        return;
      }
      allocated = n;
    } else {
      allocated = null;
    }
    await run(() =>
      onManualMatch({
        transactionId,
        matched_type: matchedType,
        matched_id: id,
        allocated_amount: allocated,
      })
    );
    setMatchedId("");
    setAllocAmount("");
    setShowSplit(false);
  };

  const partyOptions = useMemo(() => {
    const rows = moneyIn ? customersQ.data ?? [] : vendorsQ.data ?? [];
    const existing = rows.map((row) => ({
      value: String("id" in row ? row.id : ""),
      label: moneyIn
        ? (row as { customer_name: string }).customer_name
        : (row as { vendor_name: string }).vendor_name,
    }));
    return [...existing, { value: NEW_PARTY, label: "Create new contact…" }];
  }, [customersQ.data, vendorsQ.data, moneyIn]);

  const taxOptions = useMemo(() => {
    const opts = [{ value: "0", label: "0% (no tax)" }];
    if (statutoryRate != null && statutoryRate > 0) {
      const label = settingsQ.data?.tax_label || "Tax";
      opts.push({
        value: String(statutoryRate),
        label: `${statutoryRate}% ${label} (inclusive)`,
      });
    }
    return opts;
  }, [statutoryRate, settingsQ.data?.tax_label]);

  const submitCreate = async () => {
    if (transactionId == null || txn == null) return;
    if (!createLedger.trim()) {
      setActionError("Select a ledger account");
      return;
    }
    if (!createDescription.trim()) {
      setActionError("Description is required");
      return;
    }
    const partyType: "vendor" | "customer" = moneyIn ? "customer" : "vendor";
    if (!partyChoice) {
      setActionError(moneyIn ? "Select a customer" : "Select a vendor");
      return;
    }
    const rate = Number(taxRate);
    if (!Number.isFinite(rate)) {
      setActionError("Select a tax rate");
      return;
    }
    const body =
      partyChoice === NEW_PARTY
        ? {
            party_type: partyType,
            create_party: { name: newPartyName.trim() },
            ledger: createLedger.trim(),
            description: createDescription.trim(),
            tax_rate_percent: rate,
          }
        : {
            party_type: partyType,
            party_id: Number(partyChoice),
            ledger: createLedger.trim(),
            description: createDescription.trim(),
            tax_rate_percent: rate,
          };
    if (partyChoice === NEW_PARTY && !newPartyName.trim()) {
      setActionError("Enter a contact name");
      return;
    }
    await run(() => onCreateJournal(transactionId, body));
  };

  const pickerPlaceholder =
    matchedType === "collection"
      ? "Search customer or invoice…"
      : "Search vendor or invoice…";

  const confirmCopy =
    pendingConfirm?.kind === "reject"
      ? {
          title: "Reject this suggestion?",
          description: "It will be removed from review. The bank line stays unmatched.",
          confirmLabel: "Reject",
        }
      : pendingConfirm?.kind === "unmatch"
        ? {
            title: "Remove this match?",
            description: "The bank line will return to the review queue.",
            confirmLabel: "Unmatch",
          }
        : pendingConfirm?.kind === "exclude"
          ? {
              title: "Exclude this bank line?",
              description: "It will leave matching. You can still see it under Excluded.",
              confirmLabel: "Exclude",
            }
          : pendingConfirm?.kind === "reverseCreate"
            ? {
                title: "Reverse this entry?",
                description:
                  "A reversing journal will be posted as of today. The bank line returns to Unmatched.",
                confirmLabel: "Reverse this entry",
              }
            : null;

  return (
    <DetailDrawer
      open={open}
      onClose={onClose}
      title={txn ? txn.description : "Bank transaction"}
      subtitle={
        txn
          ? `${txn.txn_date} · ${money(txn.amount, txn.currency)}${
              statusLabel ? ` · ${statusLabel}` : ""
            }`
          : undefined
      }
      size="lg"
      testId="bank-feed-txn-drawer"
    >
      <div className="space-y-4">
        {detailQ.isLoading && (
          <p className="text-sm text-muted-foreground">Loading transaction…</p>
        )}
        {detailQ.isError && (
          <p className="text-sm text-destructive">Could not load transaction.</p>
        )}
        {txn && (
          <>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">Amount</p>
                <p className="tnum font-semibold">{money(txn.amount, txn.currency)}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Direction</p>
                <p className="font-medium">
                  {txn.money_flow === "in" ? "Money in" : "Money out"}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Reference</p>
                <p className="font-medium">{txn.reference || "—"}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Status</p>
                <p className="font-medium">{statusLabel}</p>
              </div>
            </div>

            <section className="space-y-2 rounded-md border border-border p-3">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                Category
              </h3>
              {unmatched ? (
                <>
                  {txn.category_coa ? (
                    <p className="text-sm font-medium" data-testid="bf-category-label">
                      {txn.category_coa}
                    </p>
                  ) : (
                    <p className="text-sm text-muted-foreground">No category yet.</p>
                  )}
                  {txn.category_source === "rule" && txn.category_rule_name ? (
                    <p className="text-xs text-muted-foreground" data-testid="bf-category-why">
                      Rule “{txn.category_rule_name}”
                      {txn.category_matched_snippet
                        ? ` matched “${txn.category_matched_snippet}”`
                        : ""}
                      . Metadata only — this does not post to the GL.
                    </p>
                  ) : txn.category_source === "manual" ? (
                    <p className="text-xs text-muted-foreground">
                      Set manually. Metadata only — this does not post to the GL.
                    </p>
                  ) : (
                    <p className="text-xs text-muted-foreground">
                      Bank narration rules apply only while unmatched. Matching a payment
                      or collection clears this category.
                    </p>
                  )}
                  <div className="flex flex-wrap gap-2 items-center">
                    <Select
                      value={categoryDraft}
                      onValueChange={setCategoryDraft}
                      options={mergeCoaOptionsWithSavedValue(
                        ledgerOptions,
                        categoryDraft || txn.category_coa || ""
                      )}
                      placeholder={coaLoading ? "Loading…" : "Assign GL category"}
                      searchable
                      disabled={!canPost || busy || coaLoading}
                      size="md"
                      className="min-w-[16rem] flex-1"
                      data-testid="bf-category-select"
                    />
                    <Button
                      size="sm"
                      disabled={
                        busy ||
                        !canPost ||
                        (categoryDraft || "") === (txn.category_coa || "")
                      }
                      onClick={() =>
                        void run(() =>
                          onSetCategory({
                            transactionId: txn.id,
                            category_coa: categoryDraft.trim() || null,
                          })
                        )
                      }
                      data-testid="bf-category-save"
                    >
                      Save
                    </Button>
                  </div>
                </>
              ) : posted ? (
                <p className="text-xs text-muted-foreground">
                  Posted to the ledger
                  {txn.category_coa ? ` as ${txn.category_coa}` : ""}. Reverse the
                  journal to edit matching or category.
                </p>
              ) : (
                <p className="text-xs text-muted-foreground">
                  This line is matched or excluded — bank narration category is not used.
                </p>
              )}
            </section>

            {unmatched && (
              <section className="space-y-2 rounded-md border border-border p-3">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Create journal
                </h3>
                <p className="text-xs text-muted-foreground">
                  Post this unmatched line to the GL. Tax is inclusive of the bank
                  amount. Contact is required.
                </p>
                <Select
                  value={partyChoice}
                  onValueChange={setPartyChoice}
                  options={partyOptions}
                  placeholder={moneyIn ? "Select customer" : "Select vendor"}
                  searchable
                  disabled={!canPost || busy}
                  size="md"
                  className="min-w-[16rem]"
                  data-testid="bf-create-party"
                />
                {partyChoice === NEW_PARTY && (
                  <input
                    type="text"
                    placeholder="New contact name"
                    value={newPartyName}
                    onChange={(e) => setNewPartyName(e.target.value)}
                    disabled={!canPost || busy}
                    className="h-9 w-full rounded-md border border-input bg-background px-2 text-sm"
                    data-testid="bf-create-party-name"
                  />
                )}
                <Select
                  value={createLedger}
                  onValueChange={setCreateLedger}
                  options={mergeCoaOptionsWithSavedValue(
                    createLedgerOptions,
                    createLedger
                  )}
                  placeholder={createCoaLoading ? "Loading…" : "Ledger account"}
                  searchable
                  disabled={!canPost || busy || createCoaLoading}
                  size="md"
                  className="min-w-[16rem]"
                  data-testid="bf-create-ledger"
                />
                <Select
                  value={taxRate}
                  onValueChange={setTaxRate}
                  options={taxOptions}
                  disabled={!canPost || busy}
                  size="md"
                  className="min-w-[12rem]"
                  data-testid="bf-create-tax"
                />
                <textarea
                  value={createDescription}
                  onChange={(e) => setCreateDescription(e.target.value)}
                  disabled={!canPost || busy}
                  rows={2}
                  className="w-full rounded-md border border-input bg-background px-2 py-1.5 text-sm"
                  data-testid="bf-create-description"
                />
                <Button
                  size="sm"
                  disabled={busy || !canPost}
                  onClick={() => void submitCreate()}
                  data-testid="bf-create-submit"
                >
                  <BookPlus className="h-4 w-4 mr-1" /> Create
                </Button>
              </section>
            )}

            {posted && (
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="border-destructive/40 text-destructive"
                  disabled={busy || !canPost}
                  onClick={() => setPendingConfirm({ kind: "reverseCreate" })}
                  data-testid="bf-reverse-create"
                >
                  <Undo2 className="h-4 w-4 mr-1" /> Reverse this entry
                </Button>
              </div>
            )}

            {suggested.length > 0 && (
              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Suggested matches
                </h3>
                {suggested.map((m) => {
                  const reasons = formatMatchReasonsPlain(m.match_reasons);
                  const confidencePct = Math.round(m.match_confidence * 100);
                  return (
                    <div
                      key={m.id}
                      className="rounded-md border border-border px-3 py-2 space-y-2"
                      data-testid={`suggested-match-${m.id}`}
                    >
                      <div className="text-sm space-y-1">
                        <p className="font-medium">{formatMatchEntityLabel(m)}</p>
                        <p className="text-xs text-muted-foreground">
                          {reasons
                            ? `${reasons} · ${confidencePct}% confidence`
                            : `${confidencePct}% confidence`}
                        </p>
                        <p className="text-xs text-muted-foreground">
                          Link amount {money(m.allocated_amount, txn.currency)}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        <Button
                          size="sm"
                          disabled={busy || !canPost}
                          onClick={() => void run(() => onConfirm(m.id))}
                          data-testid={`confirm-match-${m.id}`}
                        >
                          <Check className="h-4 w-4 mr-1" /> Confirm
                        </Button>
                        <Button
                          size="sm"
                          variant="outline"
                          className="border-destructive/40 text-destructive"
                          disabled={busy || !canPost}
                          onClick={() => setPendingConfirm({ kind: "reject", matchId: m.id })}
                          data-testid={`reject-match-${m.id}`}
                        >
                          <X className="h-4 w-4 mr-1" /> Reject
                        </Button>
                      </div>
                    </div>
                  );
                })}
              </section>
            )}

            {confirmed.length > 0 && (
              <section className="space-y-2">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Active matches
                </h3>
                {confirmed.map((m) => (
                  <div
                    key={m.id}
                    className="rounded-md border border-border px-3 py-2 flex items-center justify-between gap-2"
                  >
                    <div className="text-sm">
                      <p className="font-medium">{formatMatchEntityLabel(m)}</p>
                      <p className="text-xs text-muted-foreground">
                        {formatMatchMethodLabel(m.match_method)} ·{" "}
                        {money(m.allocated_amount, txn.currency)}
                      </p>
                      {formatMatchReasonsPlain(m.match_reasons) ? (
                        <p className="text-xs text-muted-foreground mt-0.5">
                          {formatMatchReasonsPlain(m.match_reasons)}
                        </p>
                      ) : null}
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={busy || !canPost}
                      onClick={() => setPendingConfirm({ kind: "unmatch", matchId: m.id })}
                      data-testid={`unmatch-${m.id}`}
                    >
                      <Undo2 className="h-4 w-4 mr-1" /> Unmatch
                    </Button>
                  </div>
                ))}
              </section>
            )}

            {txn.match_status !== "excluded" && !posted && (
              <section className="space-y-2 rounded-md border border-dashed border-border p-3">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                  Manual match
                </h3>
                <p className="text-xs text-muted-foreground">
                  {matchedType === "collection"
                    ? "Link this money-in line to a collection"
                    : "Link this money-out line to a payment"}
                </p>
                <div className="flex flex-wrap gap-2 items-center">
                  <Select
                    value={matchedId}
                    onValueChange={setMatchedId}
                    options={targetOptions}
                    placeholder={
                      targetsQ.isLoading ? "Loading…" : pickerPlaceholder
                    }
                    searchable
                    searchInValue={false}
                    disabled={!canPost || busy || targetsQ.isLoading}
                    size="md"
                    className="min-w-[16rem] flex-1"
                    data-testid="manual-match-target"
                  />
                  <Button
                    size="sm"
                    disabled={busy || !canPost || !matchedId}
                    onClick={() => void submitManual(false)}
                    data-testid="manual-match-submit"
                  >
                    <Link2 className="h-4 w-4 mr-1" /> Match
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={!canPost || busy}
                    onClick={() => setShowSplit((s) => !s)}
                    data-testid="manual-match-split-toggle"
                  >
                    <Split className="h-4 w-4 mr-1" /> Split
                  </Button>
                </div>
                {targetsQ.isError && (
                  <p className="text-xs text-destructive">
                    Could not load {matchedType === "collection" ? "collections" : "payments"}.
                  </p>
                )}
                {!targetsQ.isLoading &&
                  !targetsQ.isError &&
                  targetOptions.length === 0 && (
                    <p className="text-xs text-muted-foreground">
                      No matchable{" "}
                      {matchedType === "collection" ? "collections" : "payments"}{" "}
                      found.
                    </p>
                  )}
                {showSplit && (
                  <div className="flex flex-wrap gap-2 items-center">
                    <input
                      type="number"
                      min={0.01}
                      step="0.01"
                      placeholder="Amount to link"
                      value={allocAmount}
                      onChange={(e) => setAllocAmount(e.target.value)}
                      disabled={!canPost || busy}
                      className="h-9 w-40 rounded-md border border-input bg-background px-2 text-sm tnum"
                    />
                    <Button
                      size="sm"
                      disabled={busy || !canPost || !matchedId}
                      onClick={() => void submitManual(true)}
                      data-testid="manual-match-split-submit"
                    >
                      Apply split
                    </Button>
                  </div>
                )}
              </section>
            )}

            {txn.match_status !== "excluded" && !posted && (
              <div className="flex flex-wrap gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  className="border-destructive/40 text-destructive"
                  disabled={busy || !canPost}
                  onClick={() => setPendingConfirm({ kind: "exclude" })}
                  data-testid="exclude-txn"
                >
                  <Ban className="h-4 w-4 mr-1" /> Exclude
                </Button>
                {!canPost && (
                  <p className="text-xs text-muted-foreground self-center">
                    Post privilege required to change match state.
                  </p>
                )}
              </div>
            )}

            {actionError && (
              <p className={cn("text-sm text-destructive")} role="alert">
                {actionError}
              </p>
            )}

            <BankFeedTxnAuditTrail
              entries={auditQ.data ?? []}
              loading={auditQ.isLoading}
              error={auditQ.isError ? "Could not load audit trail." : null}
            />
          </>
        )}
      </div>

      <ConfirmDialog
        open={pendingConfirm != null}
        title={confirmCopy?.title ?? "Confirm"}
        description={confirmCopy?.description}
        confirmLabel={confirmCopy?.confirmLabel}
        destructive
        busy={busy}
        onCancel={() => setPendingConfirm(null)}
        onConfirm={() => {
          const pending = pendingConfirm;
          setPendingConfirm(null);
          if (!pending || !txn) return;
          if (pending.kind === "reject") {
            void run(() => onRejectSuggestion(pending.matchId));
          } else if (pending.kind === "unmatch") {
            void run(() => onUnmatch(pending.matchId));
          } else if (pending.kind === "reverseCreate") {
            void run(() => onReverseCreate(txn.id));
          } else {
            void run(() => onExclude(txn.id, "Excluded from review"));
          }
        }}
        data-testid="bf-confirm-dialog"
      />
    </DetailDrawer>
  );
}
