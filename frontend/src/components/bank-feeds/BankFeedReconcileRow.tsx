import { useRef, useState } from "react";
import type { BankAccount, BankTransaction } from "@/api/types";
import { BankFeedOkButton } from "@/components/bank-feeds/BankFeedOkButton";
import {
  BankFeedReconcilePanel,
  isReconcileOkEnabled,
  useReconcileFormState,
  type ReconcileTab,
} from "@/components/bank-feeds/BankFeedReconcilePanel";
import { BankFeedStatementCard } from "@/components/bank-feeds/BankFeedStatementCard";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useBankTransaction } from "@/hooks/useBankFeeds";

const NEW_PARTY = "__new__";

export function BankFeedReconcileRow({
  summary,
  accounts,
  canPost,
  busy,
  onConfirm,
  onManualMatch,
  onCreateJournal,
  onTransfer,
  onExclude,
  onPostNote,
}: {
  summary: BankTransaction;
  accounts: BankAccount[];
  canPost: boolean;
  busy: boolean;
  onConfirm: (matchId: number) => Promise<void>;
  onManualMatch: (args: {
    transactionId: number;
    matched_type: "payment" | "collection";
    matched_id: number;
    allocated_amount?: number | null;
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
  onTransfer: (args: {
    transactionId: number;
    to_bank_account_id: number;
    description: string;
  }) => Promise<void>;
  onExclude: (transactionId: number) => Promise<void>;
  onPostNote: (transactionId: number, body: string) => Promise<void>;
}) {
  const detailQ = useBankTransaction(summary.id, true);
  const txn = detailQ.data ?? summary;
  const [activeTab, setActiveTab] = useState<ReconcileTab>(
    txn.match_status === "suggested" ? "match" : "create"
  );
  const [actionError, setActionError] = useState<string | null>(null);
  const [excludeOpen, setExcludeOpen] = useState(false);
  const matchTargetRef = useRef<HTMLDivElement>(null);
  const form = useReconcileFormState(txn);

  const okEnabled = isReconcileOkEnabled(activeTab, txn, form);

  const runOk = async () => {
    setActionError(null);
    try {
      if (activeTab === "match") {
        if (form.matchedId) {
          const id = Number(form.matchedId);
          if (!Number.isFinite(id) || id < 1) {
            setActionError("Select a match target");
            return;
          }
          let allocated: number | null | undefined = null;
          if (form.showSplit || form.allocAmount.trim()) {
            const n = Number(form.allocAmount);
            if (!Number.isFinite(n) || n <= 0) {
              setActionError("Enter a positive split amount");
              return;
            }
            allocated = n;
          }
          const matched_type = txn.money_flow === "in" ? "collection" : "payment";
          await onManualMatch({
            transactionId: txn.id,
            matched_type,
            matched_id: id,
            allocated_amount: allocated,
          });
          return;
        }
        if (form.selectedSuggestionId != null) {
          await onConfirm(form.selectedSuggestionId);
          return;
        }
        setActionError("Select a suggestion or match target");
        return;
      } else if (activeTab === "create") {
        const moneyIn = txn.money_flow === "in";
        const partyType = moneyIn ? "customer" : "vendor";
        const rate = Number(form.taxRate);
        const body =
          form.partyChoice === NEW_PARTY
            ? {
                party_type: partyType as "vendor" | "customer",
                create_party: { name: form.newPartyName.trim() },
                ledger: form.createLedger.trim(),
                description: form.createDescription.trim(),
                tax_rate_percent: rate,
              }
            : {
                party_type: partyType as "vendor" | "customer",
                party_id: Number(form.partyChoice),
                ledger: form.createLedger.trim(),
                description: form.createDescription.trim(),
                tax_rate_percent: rate,
              };
        await onCreateJournal(txn.id, body);
      } else if (activeTab === "transfer") {
        await onTransfer({
          transactionId: txn.id,
          to_bank_account_id: Number(form.transferAccountId),
          description: form.transferDescription.trim(),
        });
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Action failed");
    }
  };

  const focusMatch = () => {
    setActiveTab("match");
    requestAnimationFrame(() => {
      matchTargetRef.current?.querySelector<HTMLElement>("button, input")?.focus();
    });
  };

  return (
    <div
      className="relative flex min-w-[52rem] items-stretch gap-3 border-b border-[#d8dee4]/80 bg-[#eef2f4] px-3 py-3 last:border-b-0 dark:border-border/60 dark:bg-muted/20"
      data-testid={`bf-reconcile-row-${txn.id}`}
    >
      <BankFeedStatementCard
        txn={txn}
        canPost={canPost}
        busy={busy}
        onExclude={() => setExcludeOpen(true)}
      />

      <div className="flex w-14 shrink-0 items-center justify-center self-center">
        {activeTab !== "discuss" ? (
          <BankFeedOkButton
            disabled={!canPost || !okEnabled}
            busy={busy}
            onClick={() => void runOk()}
          />
        ) : null}
      </div>

      <BankFeedReconcilePanel
        txn={txn}
        accounts={accounts}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        form={form}
        canPost={canPost}
        busy={busy}
        matchTargetRef={matchTargetRef}
        onFindMatch={focusMatch}
        onPostNote={(body) => onPostNote(txn.id, body)}
      />

      {actionError ? (
        <p className="absolute bottom-1 left-3 right-3 text-xs text-destructive" role="alert">
          {actionError}
        </p>
      ) : null}

      <ConfirmDialog
        open={excludeOpen}
        title="Exclude this bank line?"
        description="It will leave matching. You can still see it under Excluded."
        confirmLabel="Exclude"
        destructive
        busy={busy}
        onCancel={() => setExcludeOpen(false)}
        onConfirm={() => {
          setExcludeOpen(false);
          void onExclude(txn.id);
        }}
        data-testid={`bf-exclude-dialog-${txn.id}`}
      />
    </div>
  );
}
