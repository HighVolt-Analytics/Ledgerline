import { describe, expect, it } from "vitest";

import { normalizeTeamExpenseKind } from "./routePageAdapters";
import { teamExpensePostingPreview } from "./teamExpensePosting";

const LEDGERS = {
  expenseLedger: "Travel Expense",
  advanceLedger: "Marcus Webb",
  settlementLedger: "Bank Account",
};

describe("teamExpensePostingPreview", () => {
  it("debits the employee advance and credits settlement for an advance requisition", () => {
    const preview = teamExpensePostingPreview("advance_requisition", LEDGERS);
    expect(preview.debit).toBe("Marcus Webb");
    expect(preview.credit).toBe("Bank Account");
  });

  it("credits the employee advance when expenses clear an advance", () => {
    const preview = teamExpensePostingPreview("expense_against_advance", LEDGERS);
    expect(preview.debit).toBe("Travel Expense");
    expect(preview.credit).toBe("Marcus Webb");
  });

  it("credits settlement for a reimbursed expense claim", () => {
    const preview = teamExpensePostingPreview("expense_claim", LEDGERS);
    expect(preview.debit).toBe("Travel Expense");
    expect(preview.credit).toBe("Bank Account");
  });

  it("falls back to readable placeholders when a ledger is unset", () => {
    const preview = teamExpensePostingPreview("expense_claim", {
      expenseLedger: "",
      advanceLedger: "",
      settlementLedger: "",
    });
    expect(preview.debit).toBe("Expense ledger");
    expect(preview.credit).toBe("Settlement");
  });
});

describe("normalizeTeamExpenseKind", () => {
  it("treats unknown and empty kinds as expense claims", () => {
    expect(normalizeTeamExpenseKind(null)).toBe("expense_claim");
    expect(normalizeTeamExpenseKind("")).toBe("expense_claim");
    expect(normalizeTeamExpenseKind("nonsense")).toBe("expense_claim");
  });

  it("accepts the supported kinds case-insensitively", () => {
    expect(normalizeTeamExpenseKind("Advance_Requisition")).toBe("advance_requisition");
    expect(normalizeTeamExpenseKind("expense_against_advance")).toBe("expense_against_advance");
  });
});
