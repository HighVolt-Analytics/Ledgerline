import { describe, expect, it } from "vitest";
import type { Invoice, MatrixRow } from "@/api/types";
import {
  duplicateCellValue,
  duplicateNotificationCopy,
  isDuplicateNotificationRow,
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

describe("isDuplicateNotificationRow", () => {
  it("flags hard skips and soft review", () => {
    expect(
      isDuplicateNotificationRow(row({ invoice: inv({ status: "duplicate_skipped" }) }))
    ).toBe(true);
    expect(
      isDuplicateNotificationRow(
        row({ invoice: inv({ duplicate_review_suggested: true }) })
      )
    ).toBe(true);
    expect(isDuplicateNotificationRow(row({ flag: "Duplicate Suspected" }))).toBe(true);
    expect(isDuplicateNotificationRow(row({ conflict_with: "DOC-2" }))).toBe(true);
    expect(isDuplicateNotificationRow(row())).toBe(false);
  });
});

describe("duplicateNotificationCopy", () => {
  it("uses conflict wording when conflict_with is set", () => {
    expect(duplicateNotificationCopy(row({ conflict_with: "INV-9" })).title).toBe(
      "Duplicate conflict"
    );
  });
});

describe("normalizeAuthSyncLabel", () => {
  it("normalizes blanks to dash", () => {
    expect(normalizeAuthSyncLabel(null)).toBe("—");
    expect(normalizeAuthSyncLabel("")).toBe("—");
    expect(normalizeAuthSyncLabel("Done")).toBe("Done");
  });
});
