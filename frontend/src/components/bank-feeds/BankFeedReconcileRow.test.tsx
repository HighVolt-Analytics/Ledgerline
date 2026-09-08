/**
 * @vitest-environment happy-dom
 */
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { BankAccount, BankTransaction } from "@/api/types";
import { BankFeedReconcileRow } from "@/components/bank-feeds/BankFeedReconcileRow";
import { isReconcileOkEnabled, useReconcileFormState } from "@/components/bank-feeds/BankFeedReconcilePanel";

vi.mock("@/hooks/useBankFeeds", () => ({
  useBankTransaction: () => ({
    data: undefined,
    isLoading: false,
  }),
  useBankMatchTargets: () => ({ data: [], isLoading: false }),
  useBankTransactionNotes: () => ({ data: [], isLoading: false }),
}));

vi.mock("@/hooks/useCoaAccountOptions", () => ({
  useCoaAccountOptions: () => ({ options: [], isLoading: false }),
}));

vi.mock("@/hooks/useInstitutionSettings", () => ({
  useInstitutionSettings: () => ({ data: { statutory_tax_rate: 10, tax_label: "GST" } }),
}));

vi.mock("@/hooks/useTenantQuery", () => ({
  useTenantQuery: () => ({ data: [], isLoading: false }),
}));

const baseTxn: BankTransaction = {
  id: 1,
  bank_account_id: 10,
  import_id: 5,
  txn_date: "2026-07-27",
  posted_date: null,
  description: "Apollo.io",
  amount: 212.93,
  currency: "AUD",
  money_flow: "out",
  balance: null,
  reference: "CARD",
  match_status: "unmatched",
  category_coa: "Software Subscriptions",
  category_source: "rule",
  category_rule_name: "SaaS",
  category_matched_snippet: "apollo",
  possible_duplicate_of: null,
  posted_journal_batch_id: null,
  created_at: "2026-07-27T00:00:00Z",
  updated_at: "2026-07-27T00:00:00Z",
  matches: [],
};

const accounts: BankAccount[] = [
  {
    id: 10,
    name: "Ops",
    currency: "AUD",
    account_number: null,
    account_mask: null,
    coa_account_code: "1000",
    coa_account_name: "Bank",
    connection_type: "manual",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
  {
    id: 11,
    name: "Savings",
    currency: "AUD",
    account_number: null,
    account_mask: null,
    coa_account_code: "1001",
    coa_account_name: "Savings Bank",
    connection_type: "manual",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  },
];

describe("BankFeedReconcileRow", () => {
  afterEach(() => cleanup());

  it("renders Spent vs Received for money-out", () => {
    render(
      <BankFeedReconcileRow
        summary={baseTxn}
        accounts={accounts}
        canPost
        busy={false}
        onConfirm={async () => {}}
        onManualMatch={async () => {}}
        onCreateJournal={async () => {}}
        onTransfer={async () => {}}
        onExclude={async () => {}}
        onPostNote={async () => {}}
      />
    );
    expect(screen.getByTestId("bf-statement-1").textContent).toContain("212.93");
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("renders Received for money-in", () => {
    render(
      <BankFeedReconcileRow
        summary={{ ...baseTxn, money_flow: "in" }}
        accounts={accounts}
        canPost
        busy={false}
        onConfirm={async () => {}}
        onManualMatch={async () => {}}
        onCreateJournal={async () => {}}
        onTransfer={async () => {}}
        onExclude={async () => {}}
        onPostNote={async () => {}}
      />
    );
    expect(screen.getByTestId("bf-statement-1").textContent).toContain("212.93");
  });
});

describe("isReconcileOkEnabled", () => {
  it("disables create OK until Who What Why filled", () => {
    const txn = baseTxn;
    const form = {
      moneyIn: false,
      partyChoice: "",
      newPartyName: "",
      createLedger: "",
      createDescription: "",
      taxRate: "0",
      matchedId: "",
      allocAmount: "",
      showSplit: false,
      transferAccountId: "",
      transferDescription: "",
      selectedSuggestionId: null,
      setPartyChoice: () => {},
      setNewPartyName: () => {},
      setCreateLedger: () => {},
      setCreateDescription: () => {},
      setTaxRate: () => {},
      setMatchedId: () => {},
      setAllocAmount: () => {},
      setShowSplit: () => {},
      setTransferAccountId: () => {},
      setTransferDescription: () => {},
      setSelectedSuggestionId: () => {},
    };
    expect(isReconcileOkEnabled("create", txn, form)).toBe(false);
    form.partyChoice = "42";
    form.createLedger = "Software";
    form.createDescription = "Apollo subscription";
    expect(isReconcileOkEnabled("create", txn, form)).toBe(true);
  });
});

describe("useReconcileFormState", () => {
  it("prefills ledger and description from txn", () => {
    function Probe() {
      const form = useReconcileFormState(baseTxn);
      return (
        <span data-testid="ledger">{form.createLedger}</span>
      );
    }
    render(<Probe />);
    expect(screen.getByTestId("ledger").textContent).toBe("Software Subscriptions");
  });
});
