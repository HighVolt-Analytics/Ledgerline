import { useEffect, useMemo, useState, type RefObject, type ReactNode } from "react";
import type { BankAccount, BankTransaction, BankTransactionMatch } from "@/api/types";
import { api } from "@/api/client";
import { Select } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import {
  useBankMatchTargets,
  useBankTransactionNotes,
} from "@/hooks/useBankFeeds";
import { useCoaAccountOptions } from "@/hooks/useCoaAccountOptions";
import { useInstitutionSettings } from "@/hooks/useInstitutionSettings";
import { useTenantQuery } from "@/hooks/useTenantQuery";
import {
  formatMatchEntityLabel,
  formatMatchReasonsPlain,
} from "@/lib/bankFeedCopy";
import { mergeCoaOptionsWithSavedValue } from "@/lib/coaAccountOptions";
import { money } from "@/lib/format";
import { queryKeys } from "@/lib/queryClient";
import { BANK_FEEDS_TRANSFER_ENABLED } from "@/lib/bankFeedFeatures";
import { cn } from "@/lib/cn";

export type ReconcileTab = "match" | "create" | "transfer" | "discuss";

const TAB_LABELS: { id: ReconcileTab; label: string }[] = [
  { id: "match", label: "Match" },
  { id: "create", label: "Create" },
  ...(BANK_FEEDS_TRANSFER_ENABLED
    ? ([{ id: "transfer", label: "Transfer" }] as const)
    : []),
  { id: "discuss", label: "Discuss" },
];

const NEW_PARTY = "__new__";

function activeMatches(txn: BankTransaction): BankTransactionMatch[] {
  return (txn.matches ?? []).filter((m) => m.unmatched_at == null);
}

export function useReconcileFormState(txn: BankTransaction | undefined) {
  const moneyIn = txn?.money_flow === "in";
  const [partyChoice, setPartyChoice] = useState("");
  const [newPartyName, setNewPartyName] = useState("");
  const [createLedger, setCreateLedger] = useState("");
  const [createDescription, setCreateDescription] = useState("");
  const [taxRate, setTaxRate] = useState("0");
  const [matchedId, setMatchedId] = useState("");
  const [allocAmount, setAllocAmount] = useState("");
  const [showSplit, setShowSplit] = useState(false);
  const [transferAccountId, setTransferAccountId] = useState("");
  const [transferDescription, setTransferDescription] = useState("");
  const [selectedSuggestionId, setSelectedSuggestionId] = useState<number | null>(null);

  useEffect(() => {
    setPartyChoice("");
    setNewPartyName("");
    setCreateLedger(txn?.category_coa ?? "");
    setCreateDescription(txn?.description ?? "");
    setTaxRate("0");
    setMatchedId("");
    setAllocAmount("");
    setShowSplit(false);
    setTransferAccountId("");
    setTransferDescription(txn?.description ?? "");
    const suggested = (txn ? activeMatches(txn) : []).filter(
      (m) => m.match_method === "suggested"
    );
    setSelectedSuggestionId(suggested[0]?.id ?? null);
  }, [txn?.id, txn?.category_coa, txn?.description]);

  return {
    moneyIn,
    partyChoice,
    setPartyChoice,
    newPartyName,
    setNewPartyName,
    createLedger,
    setCreateLedger,
    createDescription,
    setCreateDescription,
    taxRate,
    setTaxRate,
    matchedId,
    setMatchedId,
    allocAmount,
    setAllocAmount,
    showSplit,
    setShowSplit,
    transferAccountId,
    setTransferAccountId,
    transferDescription,
    setTransferDescription,
    selectedSuggestionId,
    setSelectedSuggestionId,
  };
}

export function BankFeedReconcilePanel({
  txn,
  accounts,
  activeTab,
  onTabChange,
  form,
  canPost,
  busy,
  onPostNote,
  matchTargetRef,
  onFindMatch,
}: {
  txn: BankTransaction;
  accounts: BankAccount[];
  activeTab: ReconcileTab;
  onTabChange: (tab: ReconcileTab) => void;
  form: ReturnType<typeof useReconcileFormState>;
  canPost: boolean;
  busy: boolean;
  onPostNote: (body: string) => Promise<void>;
  matchTargetRef?: RefObject<HTMLDivElement>;
  onFindMatch?: () => void;
}) {
  const {
    moneyIn,
    partyChoice,
    setPartyChoice,
    newPartyName,
    setNewPartyName,
    createLedger,
    setCreateLedger,
    createDescription,
    setCreateDescription,
    taxRate,
    setTaxRate,
    matchedId,
    setMatchedId,
    allocAmount,
    setAllocAmount,
    showSplit,
    setShowSplit,
    transferAccountId,
    setTransferAccountId,
    transferDescription,
    setTransferDescription,
    selectedSuggestionId,
    setSelectedSuggestionId,
  } = form;

  const { options: createLedgerOptions, isLoading: createCoaLoading } = useCoaAccountOptions({
    includeEmpty: false,
    enabled: true,
  });
  const settingsQ = useInstitutionSettings(true);
  const statutoryRate = settingsQ.data?.statutory_tax_rate ?? null;

  const vendorsQ = useTenantQuery({
    queryKey: queryKeys.vendors(),
    queryFn: () => api.listVendors({ fresh: true }),
    enabled: !moneyIn,
  });
  const customersQ = useTenantQuery({
    queryKey: queryKeys.customers(),
    queryFn: () => api.listCustomers({ fresh: true }),
    enabled: moneyIn,
  });

  const matchedType: "payment" | "collection" = moneyIn ? "collection" : "payment";
  const targetsQ = useBankMatchTargets(matchedType, txn.bank_account_id, true);
  const notesQ = useBankTransactionNotes(txn.id, activeTab === "discuss");
  const [noteDraft, setNoteDraft] = useState("");
  const [noteError, setNoteError] = useState<string | null>(null);

  const targetOptions = useMemo(
    () =>
      (targetsQ.data ?? []).map((t) => ({
        value: String(t.id),
        label: t.display_label,
      })),
    [targetsQ.data]
  );

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

  const transferOptions = useMemo(
    () =>
      accounts
        .filter((a) => a.id !== txn.bank_account_id)
        .map((a) => ({
          value: String(a.id),
          label: `${a.name} (${a.currency})`,
        })),
    [accounts, txn.bank_account_id]
  );

  const suggested = activeMatches(txn).filter((m) => m.match_method === "suggested");

  const postNote = async () => {
    setNoteError(null);
    if (!noteDraft.trim()) {
      setNoteError("Enter a comment");
      return;
    }
    try {
      await onPostNote(noteDraft.trim());
      setNoteDraft("");
    } catch (err) {
      setNoteError(err instanceof Error ? err.message : "Could not post note");
    }
  };

  return (
    <div
      className="flex min-w-0 flex-1 flex-col rounded-sm border border-[#d8dee4] bg-card shadow-sm dark:border-border"
      data-testid={`bf-reconcile-panel-${txn.id}`}
    >
      <div className="flex shrink-0 items-center border-b border-[#d8dee4] px-2 dark:border-border">
        <div className="flex min-w-0 flex-1">
          {TAB_LABELS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => onTabChange(tab.id)}
              className={cn(
                "border-b-2 px-3 py-2.5 text-sm font-medium transition-colors -mb-px",
                activeTab === tab.id
                  ? "border-[#008abf] text-[#008abf]"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              )}
              data-testid={`bf-tab-${tab.id}-${txn.id}`}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {activeTab !== "match" && onFindMatch ? (
          <button
            type="button"
            className="shrink-0 px-2 py-2 text-sm text-[#008abf] hover:underline"
            onClick={onFindMatch}
            data-testid={`bf-find-match-${txn.id}`}
          >
            Find &amp; Match
          </button>
        ) : null}
      </div>

      <div className="p-3">
        {activeTab === "match" && (
          <div className="space-y-2" ref={matchTargetRef}>
            {suggested.length > 0 ? (
              <div className="space-y-1.5">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
                  Suggested
                </p>
                {suggested.map((m) => {
                  const reasons = formatMatchReasonsPlain(m.match_reasons);
                  const confidencePct = Math.round(m.match_confidence * 100);
                  return (
                    <label
                      key={m.id}
                      className={cn(
                        "flex gap-2 rounded border p-1.5 cursor-pointer text-xs",
                        selectedSuggestionId === m.id
                          ? "border-[#008abf] bg-[#008abf]/5"
                          : "border-border"
                      )}
                    >
                      <input
                        type="radio"
                        name={`suggestion-${txn.id}`}
                        checked={selectedSuggestionId === m.id}
                        onChange={() => setSelectedSuggestionId(m.id)}
                        className="mt-0.5 shrink-0"
                      />
                      <span className="min-w-0">
                        <span className="font-medium block truncate">{formatMatchEntityLabel(m)}</span>
                        <span className="block text-[11px] text-muted-foreground">
                          {reasons
                            ? `${reasons} · ${confidencePct}%`
                            : `${confidencePct}% confidence`}{" "}
                          · {money(m.allocated_amount, txn.currency)}
                        </span>
                      </span>
                    </label>
                  );
                })}
              </div>
            ) : null}
            <div>
              <p className="text-[11px] text-[#008abf] font-medium mb-1">Find &amp; match</p>
              <Select
                value={matchedId}
                onValueChange={setMatchedId}
                options={targetOptions}
                placeholder={
                  targetsQ.isLoading
                    ? "Loading…"
                    : matchedType === "collection"
                      ? "Search customer or invoice…"
                      : "Search vendor or invoice…"
                }
                searchable
                searchInValue={false}
                disabled={!canPost || busy || targetsQ.isLoading}
                size="sm"
                className="w-full"
                data-testid={`bf-match-target-${txn.id}`}
              />
              <div className="mt-1.5 flex gap-2 items-center">
                <Button
                  size="sm"
                  variant="outline"
                  className="h-7 text-xs"
                  disabled={!canPost || busy}
                  onClick={() => setShowSplit((s) => !s)}
                >
                  Split
                </Button>
                {showSplit && (
                  <input
                    type="number"
                    min={0.01}
                    step="0.01"
                    placeholder="Amount"
                    value={allocAmount}
                    onChange={(e) => setAllocAmount(e.target.value)}
                    disabled={!canPost || busy}
                    className="h-7 flex-1 min-w-0 rounded-md border border-input bg-background px-2 text-xs tnum"
                  />
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === "create" && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Who">
                <Select
                  value={partyChoice}
                  onValueChange={setPartyChoice}
                  options={partyOptions}
                  placeholder={moneyIn ? "Select customer" : "Select vendor"}
                  searchable
                  disabled={!canPost || busy}
                  size="sm"
                  className="w-full"
                  data-testid={`bf-create-who-${txn.id}`}
                />
                {partyChoice === NEW_PARTY && (
                  <input
                    type="text"
                    placeholder="New contact name"
                    value={newPartyName}
                    onChange={(e) => setNewPartyName(e.target.value)}
                    disabled={!canPost || busy}
                    className="mt-1 h-9 w-full rounded-sm border border-input bg-background px-2 text-sm"
                  />
                )}
              </Field>
              <Field label="What">
                <Select
                  value={createLedger}
                  onValueChange={setCreateLedger}
                  options={mergeCoaOptionsWithSavedValue(createLedgerOptions, createLedger)}
                  placeholder={createCoaLoading ? "Loading…" : "COA account"}
                  searchable
                  disabled={!canPost || busy || createCoaLoading}
                  size="sm"
                  className="w-full"
                  data-testid={`bf-create-what-${txn.id}`}
                />
              </Field>
            </div>
            <Field label="Why">
              <input
                type="text"
                value={createDescription}
                onChange={(e) => setCreateDescription(e.target.value)}
                disabled={!canPost || busy}
                placeholder="Enter a description…"
                className="h-9 w-full rounded-sm border border-input bg-background px-2 text-sm"
                data-testid={`bf-create-why-${txn.id}`}
              />
            </Field>
            <Field label="Tax Rate">
              <Select
                value={taxRate}
                onValueChange={setTaxRate}
                options={taxOptions}
                disabled={!canPost || busy}
                size="sm"
                className="w-full max-w-xs"
                data-testid={`bf-create-tax-${txn.id}`}
              />
            </Field>
          </div>
        )}

        {activeTab === "transfer" && (
          <div className="space-y-2">
            <p className="text-[11px] text-muted-foreground leading-snug">
              Use Transfer when this money moved between two of your own bank accounts — not as
              income or expense.
            </p>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 sm:items-end">
              <Field label={moneyIn ? "From account" : "To account"}>
                <Select
                  value={transferAccountId}
                  onValueChange={setTransferAccountId}
                  options={transferOptions}
                  placeholder={
                    moneyIn
                      ? "Select the account funds came from"
                      : "Select the destination account"
                  }
                  searchable
                  disabled={!canPost || busy}
                  size="sm"
                  className="w-full"
                  data-testid={`bf-transfer-account-${txn.id}`}
                />
              </Field>
              <Field label="Why">
                <input
                  type="text"
                  value={transferDescription}
                  onChange={(e) => setTransferDescription(e.target.value)}
                  disabled={!canPost || busy}
                  className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs"
                  data-testid={`bf-transfer-why-${txn.id}`}
                />
              </Field>
            </div>
          </div>
        )}

        {activeTab === "discuss" && (
          <div className="space-y-2">
            {notesQ.isLoading ? (
              <p className="text-[11px] text-muted-foreground">Loading comments…</p>
            ) : (notesQ.data ?? []).length === 0 ? (
              <p className="text-[11px] text-muted-foreground">No comments yet.</p>
            ) : (
              <ul className="space-y-1 max-h-28 overflow-y-auto">
                {(notesQ.data ?? []).map((note) => (
                  <li key={note.id} className="rounded bg-muted/40 px-2 py-1 text-[11px]">
                    <p>{note.body}</p>
                    <p className="text-muted-foreground mt-0.5">
                      {new Date(note.created_at).toLocaleString()}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <textarea
              value={noteDraft}
              onChange={(e) => setNoteDraft(e.target.value)}
              disabled={!canPost || busy}
              rows={2}
              placeholder="Add a comment…"
              className="w-full rounded-md border border-input bg-background px-2 py-1 text-xs"
              data-testid={`bf-discuss-input-${txn.id}`}
            />
            {noteError ? <p className="text-[11px] text-destructive">{noteError}</p> : null}
            <Button
              size="sm"
              className="h-7 text-xs"
              disabled={!canPost || busy || !noteDraft.trim()}
              onClick={() => void postNote()}
              data-testid={`bf-discuss-post-${txn.id}`}
            >
              Post
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <p className="mb-1 text-sm font-medium text-[#008abf]">{label}</p>
      {children}
    </div>
  );
}

export function isReconcileOkEnabled(
  tab: ReconcileTab,
  _txn: BankTransaction,
  form: ReturnType<typeof useReconcileFormState>
): boolean {
  if (tab === "discuss") return false;
  if (tab === "match") {
    if (form.selectedSuggestionId != null) return true;
    const id = Number(form.matchedId);
    if (!Number.isFinite(id) || id < 1) return false;
    if (form.showSplit || form.allocAmount.trim()) {
      const n = Number(form.allocAmount);
      return Number.isFinite(n) && n > 0;
    }
    return true;
  }
  if (tab === "create") {
    if (!form.createLedger.trim() || !form.createDescription.trim()) return false;
    if (!form.partyChoice) return false;
    if (form.partyChoice === NEW_PARTY && !form.newPartyName.trim()) return false;
    return Number.isFinite(Number(form.taxRate));
  }
  if (tab === "transfer") {
    const dest = Number(form.transferAccountId);
    return (
      Number.isFinite(dest) &&
      dest > 0 &&
      form.transferDescription.trim().length > 0
    );
  }
  return false;
}
