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

  it("partially nets available advance on an expense claim", () => {
    const preview = teamExpensePostingPreview("expense_claim", {
      ...LEDGERS,
      claimAmount: 800,
      advanceAvailable: 500,
    });
    expect(preview.debit).toBe("Travel Expense");
    expect(preview.credit).toContain("Marcus Webb");
    expect(preview.credit).toContain("Bank Account");
    expect(preview.note.toLowerCase()).toContain("nets");
  });

  it("credits settlement only when no advance float is available", () => {
    const preview = teamExpensePostingPreview("expense_claim", {
      ...LEDGERS,
      claimAmount: 100,
      advanceAvailable: 0,
    });
    expect(preview.debit).toBe("Travel Expense");
    expect(preview.credit).toBe("Bank Account");
  });

  it("posts expense and settlement only for direct payment", () => {
    const preview = teamExpensePostingPreview("direct_payment", {
      ...LEDGERS,
      claimAmount: 500,
      advanceAvailable: 200,
    });
    expect(preview.debit).toBe("Travel Expense");
    expect(preview.credit).toBe("Bank Account");
    expect(preview.note.toLowerCase()).toContain("no advance");
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

  it("accepts the supported kinds case-insensitively and maps legacy against-advance to claim", () => {
    expect(normalizeTeamExpenseKind("Advance_Requisition")).toBe("advance_requisition");
    expect(normalizeTeamExpenseKind("expense_against_advance")).toBe("expense_claim");
    expect(normalizeTeamExpenseKind("direct_payment")).toBe("direct_payment");
  });
});
