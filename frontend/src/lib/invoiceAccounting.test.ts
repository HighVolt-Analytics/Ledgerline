import { describe, expect, it } from "vitest";
import type { ChartOfAccountRow, JournalEntry, PaymentApi } from "@/api/types";
import {
  drawerTabsForInvoice,
  expensePostingPipelineStatus,
  filterJournalEntriesByPosting,
  groupJournalEntries,
  invoiceAccountingPostingStatus,
  paymentPostingPipelineStatus,
  paymentStatusDisplay,
  postingRowsFromJournals,
  resolveJournalGlSelection,
} from "@/lib/invoiceAccounting";

function paymentStub(status: PaymentApi["status"]): PaymentApi {
  return {
    id: 1,
    invoice_id: 2,
    vendor: "Acme",
    amount: 100,
    currency: "AUD",
    status,
    tab: "paid",
    due_date: "2026-02-01",
    scheduled_date: null,
    paid_date: status === "paid" ? "2026-02-03" : null,
    invoice_approved_by: null,
    approvers: [],
    payment_intent: null,
    failure_reason: null,
    vendor_payout_status: null,
    vendor_payout_method_type: null,
    execution_readiness_status: null,
    execution_blocking_reason: null,
    execution_instruction: null,
  };
}

describe("invoiceAccountingPostingStatus", () => {
  it("returns blocked for exception invoices", () => {
    const result = invoiceAccountingPostingStatus({
      status: "exception",
      published_to_ledger: false,
      current_stage: "Validated",
      current_stage_state: "fail",
    });
    expect(result.label).toBe("Blocked");
    expect(result.tone).toBe("error");
  });

  it("returns success when processed", () => {
    const result = invoiceAccountingPostingStatus({
      status: "processed",
      published_to_ledger: false,
      current_stage: "Processed",
      current_stage_state: "done",
    });
    expect(result.label).toBe("Journals posted");
    expect(result.tone).toBe("success");
  });

  it("returns reconciling while in that status", () => {
    const result = invoiceAccountingPostingStatus({
      status: "reconciling",
      published_to_ledger: false,
      current_stage: "Reconciling",
      current_stage_state: "pending",
    });
    expect(result.label).toBe("Reconciling");
  });
});

describe("groupJournalEntries", () => {
  it("groups accrual before settlement", () => {
    const entries: JournalEntry[] = [
      {
        id: 2,
        invoice_id: 1,
        date: "2026-01-02",
        account_code: "2000",
        account_name: "AP",
        debit: "0",
        credit: "110",
        entry_type: "credit",
        entry_kind: "payment_settlement",
      },
      {
        id: 1,
        invoice_id: 1,
        date: "2026-01-01",
        account_code: "5000",
        account_name: "Expense",
        debit: "100",
        credit: "0",
        entry_type: "debit",
        entry_kind: "invoice_accrual",
      },
    ];

    const groups = groupJournalEntries(entries);
    expect(groups.map((g) => g.id)).toEqual(["invoice_accrual", "payment_settlement"]);
    expect(groups[0]?.entries).toHaveLength(1);
  });
});

describe("drawerTabsForInvoice", () => {
  it("inserts accounting after match when posting applies", () => {
    expect(drawerTabsForInvoice("Purchase Management", true)).toEqual([
      "fields",
      "lines",
      "po",
      "accounting",
      "audit",
      "vault",
    ]);
  });

  it("omits accounting when posting does not apply", () => {
    expect(drawerTabsForInvoice("Vault", false)).toEqual([
      "fields",
      "lines",
      "audit",
      "vault",
    ]);
  });
});

describe("paymentStatusDisplay", () => {
  it("describes missing payment", () => {
    expect(paymentStatusDisplay(null).label).toBe("Not queued");
  });

  it("describes paid payment", () => {
    expect(paymentStatusDisplay(paymentStub("paid")).label).toBe("Paid");
  });
});

describe("expense and payment posting pipelines", () => {
  it("maps expense posting to NA / In progress / Completed", () => {
    expect(
      expensePostingPipelineStatus(
        { status: "extracted", published_to_ledger: false },
        []
      ).label
    ).toBe("NA");
    expect(
      expensePostingPipelineStatus(
        { status: "journaling", published_to_ledger: false },
        []
      ).label
    ).toBe("In progress");
    expect(
      expensePostingPipelineStatus(
        { status: "processed", published_to_ledger: false },
        []
      ).label
    ).toBe("Completed");
  });

  it("maps payment posting from journals or payment status", () => {
    expect(paymentPostingPipelineStatus(null, []).label).toBe("NA");
    expect(paymentPostingPipelineStatus(paymentStub("queue"), []).label).toBe("In progress");
    expect(paymentPostingPipelineStatus(paymentStub("paid"), []).label).toBe("Completed");
  });

  it("splits expense vs payment journals and puts posting date first on rows", () => {
    const entries: JournalEntry[] = [
      {
        id: 1,
        invoice_id: 9,
        date: "2026-03-15",
        account_code: "6100",
        account_name: "Office Supplies",
        debit: "40",
        credit: "0",
        entry_type: "debit",
        entry_kind: "invoice_accrual",
      },
      {
        id: 2,
        invoice_id: 9,
        date: "2026-03-20",
        account_code: "2000",
        account_name: "Accounts Payable",
        debit: "40",
        credit: "0",
        entry_type: "debit",
        entry_kind: "payment_settlement",
      },
    ];
    expect(filterJournalEntriesByPosting(entries, "expense")).toHaveLength(1);
    expect(filterJournalEntriesByPosting(entries, "payment")).toHaveLength(1);
    const rows = postingRowsFromJournals(
      filterJournalEntriesByPosting(entries, "expense"),
      "2026-01-01"
    );
    expect(rows[0]?.postingDate).toBe("2026-03-15");
    expect(rows[0]?.side).toBe("Dr");
  });

  it("resolves ledger and subledger from COA codes", () => {
    const accounts: ChartOfAccountRow[] = [
      {
        code: "6100",
        name: "Office Expenses",
        type: "Expense",
        subLedgers: [{ code: "01", name: "Stationery" }],
      },
    ];
    expect(
      resolveJournalGlSelection(
        { accountCode: "6100-01", accountName: "Stationery" },
        accounts
      )
    ).toEqual({ ledger: "Office Expenses", subLedger: "Stationery" });
  });
});
