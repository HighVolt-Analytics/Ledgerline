import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";
import type { InvoiceDetails, PaymentApi } from "@/api/types";
import { formatMoney } from "@/components/invoice-preview/DocumentSummaryPreview";
import { SubLedgerField } from "@/components/rule-book/SubLedgerField";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useChartOfAccounts } from "@/hooks/useChartOfAccounts";
import {
  coaAccountsToSelectOptions,
  ledgerHasSubLedgerCatalog,
  mergeCoaOptionsWithSavedValue,
  subLedgerExistsInCoa,
} from "@/lib/coaAccountOptions";
import { cn } from "@/lib/cn";
import { money } from "@/lib/format";
import {
  expensePostingPipelineStatus,
  filterJournalEntriesByPosting,
  paymentPostingPipelineStatus,
  postingRowsFromJournals,
  resolveJournalGlSelection,
  type AccountingPipelineStatus,
  type AccountingPostingRow,
} from "@/lib/invoiceAccounting";

const POSTING_GRID = "minmax(6.9rem, 0.85fr) minmax(0, 1.15fr) minmax(0, 1.15fr) 4.35rem minmax(4.75rem, 0.7fr)";

const DR_CR_OPTIONS = [
  { value: "Dr", label: "Dr" },
  { value: "Cr", label: "Cr" },
];

type InvoiceDrawerAccountingSectionProps = {
  inv: InvoiceDetails;
  parentLedger: string;
  currencySymbolHint?: string | null;
  payment: PaymentApi | null;
  paymentLoading: boolean;
  editable?: boolean;
};

function toneClass(tone: AccountingPipelineStatus["tone"]): string {
  if (tone === "success") return "text-emerald-700 dark:text-emerald-400";
  if (tone === "pending") return "text-amber-700 dark:text-amber-400";
  return "text-muted-foreground";
}

function toDateInputValue(value: string): string {
  const trimmed = value.trim();
  const iso = trimmed.match(/^(\d{4}-\d{2}-\d{2})/);
  return iso?.[1] ?? "";
}

function PostingValue({ value }: { value: string }) {
  const text = value.trim();
  return (
    <span
      className={cn("text-xs block truncate text-left", !text && "text-muted-foreground")}
      title={text || undefined}
    >
      {text || "—"}
    </span>
  );
}

function PostingGlSelects({
  row,
  editable,
  onChange,
}: {
  row: AccountingPostingRow;
  editable: boolean;
  onChange: (patch: Partial<AccountingPostingRow>) => void;
}) {
  const { data: accounts = [] } = useChartOfAccounts();
  const { ledger, subLedger } = resolveJournalGlSelection(row, accounts);
  const hasSubCatalog = ledgerHasSubLedgerCatalog(ledger, accounts);
  const subInCatalog = subLedgerExistsInCoa(ledger, subLedger, accounts);
  const renderedSub = hasSubCatalog ? (subInCatalog ? subLedger : "") : "";

  const ledgerOptions = mergeCoaOptionsWithSavedValue(
    coaAccountsToSelectOptions(accounts, {
      includeEmpty: true,
      emptyLabel: "— Select ledger —",
    }),
    ledger
  );

  if (!editable) {
    return (
      <>
        <div className="px-2 py-2 min-w-0">
          <PostingValue value={ledger} />
        </div>
        <div className="px-2 py-2 min-w-0">
          <PostingValue value={renderedSub} />
        </div>
      </>
    );
  }

  return (
    <>
      <div className="px-2 py-2 min-w-0">
        <Select
          value={ledger}
          onValueChange={(value) => onChange({ ledger: value, subLedger: "" })}
          options={ledgerOptions}
          className="invoice-drawer-gl-select w-full"
          data-testid="invoice-accounting-ledger-select"
          size="sm"
        />
      </div>
      <div className="px-2 py-2 min-w-0">
        {hasSubCatalog ? (
          <SubLedgerField
            ledger={ledger}
            value={renderedSub}
            onChange={(value) => onChange({ ledger, subLedger: value })}
            accounts={accounts}
            className="invoice-drawer-gl-select w-full"
            data-testid="invoice-accounting-subledger-select"
            includeEmpty
            emptyLabel="— Select subledger —"
            size="sm"
          />
        ) : (
          <Select
            value=""
            onValueChange={() => undefined}
            options={[
              {
                value: "",
                label: ledger ? "No sub-GL catalogue" : "Select ledger first",
              },
            ]}
            className="invoice-drawer-gl-select w-full"
            data-testid="invoice-accounting-subledger-select"
            size="sm"
            disabled
          />
        )}
      </div>
    </>
  );
}

function PostingBlock({
  title,
  status,
  rows,
  resetKey,
  formatAmount,
  loading = false,
  editable = false,
  testId,
  className,
}: {
  title: string;
  status: AccountingPipelineStatus;
  rows: AccountingPostingRow[];
  resetKey: string;
  formatAmount: (value: string | null | undefined) => string;
  loading?: boolean;
  editable?: boolean;
  testId: string;
  className?: string;
}) {
  const [draftRows, setDraftRows] = useState(rows);

  useEffect(() => {
    setDraftRows(rows);
  }, [resetKey, editable]);

  function patchRow(key: string, patch: Partial<AccountingPostingRow>) {
    setDraftRows((current) =>
      current.map((row) => (row.key === key ? { ...row, ...patch } : row))
    );
  }

  const displayRows = editable ? draftRows : rows;

  return (
    <section className={cn("space-y-2", className)} data-testid={testId}>
      <div className="flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <span className={cn("text-sm font-medium shrink-0 text-right", toneClass(status.tone))}>
          {status.label}
        </span>
      </div>
      {loading ? (
        <p className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
          Loading payment…
        </p>
      ) : (
        <div className="invoice-drawer-accounting-table rounded-md border border-border">
          <div className="invoice-drawer-lines-edit text-sm">
            <div
              className="invoice-drawer-lines-edit-row invoice-drawer-lines-edit-row--head text-xs text-muted-foreground bg-muted/50"
              style={{ gridTemplateColumns: POSTING_GRID }}
            >
              <span className="px-3 py-2 font-medium">Posting Date</span>
              <span className="px-2 py-2 font-medium">Ledger</span>
              <span className="px-2 py-2 font-medium">Subledger</span>
              <span className="px-2 py-2 font-medium">Dr/Cr</span>
              <span className="px-2 py-2 font-medium">Amt</span>
            </div>
            {displayRows.map((row) => (
              <div
                key={row.key}
                className="invoice-drawer-lines-edit-row border-t border-border"
                style={{ gridTemplateColumns: POSTING_GRID }}
              >
                <div className="px-2 py-2 min-w-0">
                  {editable ? (
                    <Input
                      type="date"
                      value={toDateInputValue(row.postingDate)}
                      onChange={(event) =>
                        patchRow(row.key, { postingDate: event.target.value })
                      }
                      className="h-8 w-full min-w-0 text-sm text-left tnum block"
                      data-testid="invoice-accounting-posting-date"
                    />
                  ) : (
                    <PostingValue value={toDateInputValue(row.postingDate) || row.postingDate} />
                  )}
                </div>
                <PostingGlSelects
                  row={row}
                  editable={editable}
                  onChange={(patch) => patchRow(row.key, patch)}
                />
                <div className="px-2 py-2 min-w-0">
                  {editable ? (
                    <Select
                      value={row.side}
                      onValueChange={(value) =>
                        patchRow(row.key, { side: value === "Cr" ? "Cr" : "Dr" })
                      }
                      options={DR_CR_OPTIONS}
                      className="invoice-drawer-gl-select w-full"
                      data-testid="invoice-accounting-side-select"
                      size="sm"
                    />
                  ) : (
                    <PostingValue value={row.side} />
                  )}
                </div>
                <div className="px-2 py-2 min-w-0">
                  {editable ? (
                    <Input
                      value={row.amount ? formatAmount(row.amount) : ""}
                      readOnly
                      tabIndex={-1}
                      className="h-8 w-full min-w-0 text-sm text-left tnum block"
                    />
                  ) : (
                    <PostingValue value={row.amount ? formatAmount(row.amount) : ""} />
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

export function InvoiceDrawerAccountingSection({
  inv,
  parentLedger,
  currencySymbolHint,
  payment,
  paymentLoading,
  editable = false,
}: InvoiceDrawerAccountingSectionProps) {
  const fmt = (value: string | null | undefined) =>
    inv.currency
      ? formatMoney(value, inv.currency, undefined, currencySymbolHint)
      : money(value, inv.currency);

  const postingDate = inv.invoice_date?.trim() || "";
  const expenseEntries = filterJournalEntriesByPosting(inv.journal_entries, "expense");
  const paymentEntries = filterJournalEntriesByPosting(inv.journal_entries, "payment");
  const expenseStatus = expensePostingPipelineStatus(inv, expenseEntries);
  const paymentStatus = paymentPostingPipelineStatus(payment, paymentEntries);
  const firstLine = inv.line_items[0];
  const expenseRows = postingRowsFromJournals(expenseEntries, postingDate).map((row) => {
    if (expenseEntries.length > 0) return row;
    if (row.side === "Dr") {
      return {
        ...row,
        ledger: (firstLine?.parent_ledger ?? parentLedger).trim(),
        subLedger: (firstLine?.sub_ledger ?? "").trim(),
        amount: firstLine?.amount ?? inv.total ?? row.amount,
      };
    }
    return { ...row, amount: inv.total ?? row.amount };
  });
  const paymentRows = postingRowsFromJournals(paymentEntries, postingDate);

  return (
    <div className="invoice-drawer-accounting" data-testid="invoice-drawer-accounting-tab">
      <PostingBlock
        title="Expense Posting"
        status={expenseStatus}
        rows={expenseRows}
        resetKey={`${inv.id}-expense-${expenseEntries.map((entry) => entry.id).join(",")}`}
        formatAmount={fmt}
        editable={editable}
        testId="invoice-accounting-expense-posting"
      />
      <PostingBlock
        title="Payment Posting"
        status={paymentStatus}
        rows={paymentRows}
        resetKey={`${inv.id}-payment-${paymentEntries.map((entry) => entry.id).join(",")}`}
        formatAmount={fmt}
        editable={editable}
        loading={paymentLoading}
        testId="invoice-accounting-payment-posting"
        className="invoice-drawer-accounting__payment"
      />
    </div>
  );
}
