import { describe, expect, it } from "vitest";
import type { Invoice, MatrixRow } from "@/api/types";
import {
  duplicateCellValue,
  lineItemCellValue,
  normalizeAuthSyncLabel,
} from "@/lib/allDocumentsDetailed";

function inv(overrides: Partial<Invoice> = {}): Invoice {
  return {
    id: 1,
    status: "processed",
    vendor: "Acme",
    invoice_no: "INV-1",
    document_ref: "DOC-1",
    currency: "USD",
    total: "100",
    capture_source: "upload",
    duplicate_review_suggested: false,
    ...overrides,
  } as Invoice;
}

function row(overrides: Partial<MatrixRow> & { invoice?: Invoice } = {}): MatrixRow {
  return {
    invoice: overrides.invoice ?? inv(),
    stages: [],
    flag: "Clean",
    payment_status: "—",
    conflict_with: null,
    line_item_count: 0,
    advance_auth: "—",
    budget_auth: "—",
    acc_sync: "—",
    ...overrides,
  };
}

describe("duplicateCellValue", () => {
  it("prefers conflict_with ref", () => {
    expect(duplicateCellValue(row({ conflict_with: "DOC-9" }))).toEqual({
      label: "DOC-9",
      kind: "conflict",
    });
  });

  it("shows Possible for soft duplicate signal", () => {
    expect(
      duplicateCellValue(
        row({ invoice: inv({ duplicate_review_suggested: true }) })
      )
    ).toEqual({ label: "Possible", kind: "possible" });
  });

  it("returns empty dash otherwise", () => {
    expect(duplicateCellValue(row())).toEqual({ label: "—", kind: "empty" });
  });
});

describe("lineItemCellValue", () => {
  it("shows count when present", () => {
    expect(lineItemCellValue(row({ line_item_count: 3 }))).toBe("3");
  });

  it("shows em dash while still parsing with zero lines", () => {
    expect(
      lineItemCellValue(row({ invoice: inv({ status: "parsing" }), line_item_count: 0 }))
    ).toBe("—");
  });

  it("shows 0 when settled with no lines", () => {
    expect(lineItemCellValue(row({ line_item_count: 0 }))).toBe("0");
  });
});

describe("normalizeAuthSyncLabel", () => {
  it("normalizes blanks to dash", () => {
    expect(normalizeAuthSyncLabel(null)).toBe("—");
    expect(normalizeAuthSyncLabel("")).toBe("—");
    expect(normalizeAuthSyncLabel("Done")).toBe("Done");
  });
});
