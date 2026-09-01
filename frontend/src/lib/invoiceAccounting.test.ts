import { describe, expect, it } from "vitest";
import type { JournalEntry } from "@/api/types";
import {
  drawerTabsForInvoice,
  groupJournalEntries,
  invoiceAccountingPostingStatus,
  paymentStatusDisplay,
} from "@/lib/invoiceAccounting";

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
  it("inserts accounting after tax when posting applies", () => {
    expect(drawerTabsForInvoice("Purchase Management", true)).toEqual([
      "fields",
      "lines",
      "po",
      "tax",
      "accounting",
      "audit",
      "vault",
    ]);
  });

  it("omits accounting when posting does not apply", () => {
    expect(drawerTabsForInvoice("Vault", false)).toEqual([
      "fields",
      "lines",
      "tax",
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
    expect(
      paymentStatusDisplay({
        id: 1,
        invoice_id: 2,
        vendor: "Acme",
        amount: 100,
        currency: "AUD",
        status: "paid",
        tab: "paid",
        due_date: "2026-02-01",
        scheduled_date: null,
        paid_date: "2026-02-03",
        invoice_approved_by: null,
        approvers: [],
        payment_intent: null,
        failure_reason: null,
        vendor_payout_status: null,
        vendor_payout_method_type: null,
        execution_readiness_status: null,
        execution_blocking_reason: null,
        execution_instruction: null,
      }).label
    ).toBe("Paid");
  });
});
