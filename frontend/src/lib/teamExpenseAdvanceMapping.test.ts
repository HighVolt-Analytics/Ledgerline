import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import { mapEmployee } from "@/lib/ruleBookConfigApi";
import { invoiceToTeamClaim } from "@/lib/routePageAdapters";
import type { EmployeeMaster } from "@/lib/v4RuleBookTypes";

function baseInvoice(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: 101,
    vendor: "Unknown",
    invoice_no: "TE-1",
    document_ref: "DOC-101",
    total: "120.00",
    gst: "0",
    currency: "AUD",
    invoice_date: "2026-04-01",
    status: "exception",
    email_sender: "marcus@example.com",
    route_target: "Team Expenses",
    team_expense_kind: "expense_claim",
    created_at: "2026-04-01T10:00:00Z",
    ...overrides,
  } as Invoice;
}

const marcus: EmployeeMaster = {
  id: "em-marcus",
  name: "Marcus Webb",
  role: "Ops",
  email: "marcus@example.com",
  whatsappNumber: "",
  division: "Finance",
  location: "Sydney",
  bank: { accountNumber: "1", accountName: "Marcus", bankName: "Bank" },
  budget: { monthly: 0, quarterly: 0, annual: 0, categories: [] },
  advanceParentLedger: "Staff Advance",
  advanceSubLedger: "Marcus Webb",
  advanceBalance: 600,
  ytdSpent: 0,
  mtdSpent: 0,
  qtdSpent: 0,
  claimCount: 0,
  lastClaim: "—",
  status: "Active",
};

describe("net advance + employee identity mapping", () => {
  it("mapEmployee reads advance_balance", () => {
    const emp = mapEmployee({
      id: "em-marcus",
      name: "Marcus Webb",
      advance_balance: 250.5,
      bank: {},
      budget: {},
    });
    expect(emp.advanceBalance).toBe(250.5);
  });

  it("invoiceToTeamClaim fills master identity and advance", () => {
    const claim = invoiceToTeamClaim(baseInvoice(), [marcus]);
    expect(claim.submitter).toBe("Marcus Webb");
    expect(claim.employeeId).toBe("em-marcus");
    expect(claim.division).toBe("Finance");
    expect(claim.location).toBe("Sydney");
    expect(claim.advanceBalance).toBe(600);
  });

  it("invoiceToTeamClaim leaves identity empty when unmatched", () => {
    const claim = invoiceToTeamClaim(
      baseInvoice({ email_sender: "unknown@example.com", vendor: "Walk-in" }),
      [marcus]
    );
    expect(claim.submitter).toBe("Unknown");
    expect(claim.employeeId).toBe("");
    expect(claim.division).toBe("");
    expect(claim.location).toBe("");
    expect(claim.advanceBalance).toBe(0);
  });
});
