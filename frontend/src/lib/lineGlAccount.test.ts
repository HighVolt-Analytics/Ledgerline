import { describe, expect, it } from "vitest";

import type { ChartOfAccountRow, LineItem } from "@/api/types";
import {
  effectiveLineLedger,
  lineGlMappingReason,
  lineGlSourceLabel,
  lineSubLedgerRequired,
  suggestLineSubLedger,
} from "@/lib/lineGlAccount";

const coa: ChartOfAccountRow[] = [
  {
    code: "6110",
    name: "Cloud Hosting Expense",
    type: "Expense",
    subLedgers: [
      { code: "01", name: "AWS Production" },
      { code: "02", name: "Azure Staging" },
    ],
  },
  {
    code: "6100",
    name: "Operating Expenses",
    type: "Expense",
  },
];

const baseLine: LineItem = {
  id: 1,
  invoice_id: 1,
  description: "AWS monthly hosting",
  qty: "1",
  unit_price: "100",
  amount: "100",
  tax_amount: null,
  sub_ledger: null,
  parent_ledger: "Cloud Hosting Expense",
  effective_ledger: null,
  gl_mapping_source: "llm",
  gl_mapping_reason: "Hosting infrastructure",
};

describe("lineGlAccount", () => {
  it("uses sub-ledger as effective display when catalog exists", () => {
    expect(
      effectiveLineLedger(
        { ...baseLine, sub_ledger: "AWS Production" },
        "Cloud Hosting Expense"
      )
    ).toBe("AWS Production");
  });

  it("falls back to parent ledger when no sub-ledger", () => {
    expect(
      effectiveLineLedger(
        { ...baseLine, parent_ledger: null, effective_ledger: null, sub_ledger: null },
        "Operating Expenses"
      )
    ).toBe("Operating Expenses");
  });

  it("suggests sub-ledger from description keywords within catalog", () => {
    expect(
      suggestLineSubLedger(
        { description: "AWS monthly hosting", sub_ledger: null },
        coa,
        "Cloud Hosting Expense"
      )
    ).toBe("AWS Production");
  });

  it("labels mapping sources honestly", () => {
    expect(lineGlSourceLabel("llm")).toBe("LLM");
    expect(lineGlSourceLabel("doc_type_default")).toBe("Doc type default");
  });

  it("builds mapping reason from persisted metadata", () => {
    expect(
      lineGlMappingReason(
        { ...baseLine, sub_ledger: "AWS Production" },
        "Cloud Hosting Expense",
        true
      )
    ).toContain("LLM");
  });

  it("marks blank sub-ledger required when parent has catalogue", () => {
    expect(lineSubLedgerRequired(baseLine, "Cloud Hosting Expense", coa)).toBe(true);
    expect(
      lineSubLedgerRequired(
        { ...baseLine, sub_ledger: "AWS Production" },
        "Cloud Hosting Expense",
        coa
      )
    ).toBe(false);
    expect(lineSubLedgerRequired(baseLine, "Operating Expenses", coa)).toBe(false);
  });
});
