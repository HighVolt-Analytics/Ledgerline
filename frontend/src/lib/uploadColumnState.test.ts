import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import {
  columnHasDisplayValue,
  isInvoicePipelineActive,
  uploadColumnDisplayMode,
} from "@/lib/uploadColumnState";

function inv(id: number, status: string, extra: Partial<Invoice> = {}): Invoice {
  return {
    id,
    status,
    created_at: "2026-01-01T00:00:00Z",
    currency: "AUD",
    ...extra,
  } as Invoice;
}

describe("isInvoicePipelineActive", () => {
  it("returns true for pipeline statuses", () => {
    expect(isInvoicePipelineActive(inv(1, "pending"))).toBe(true);
    expect(isInvoicePipelineActive(inv(2, "parsing"))).toBe(true);
  });

  it("returns true when id is in processingIds and status still in-flight", () => {
    expect(isInvoicePipelineActive(inv(1, "pending"), new Set([1]))).toBe(true);
  });

  it("returns false when processingIds is set but status already settled", () => {
    expect(isInvoicePipelineActive(inv(1, "processed"), new Set([1]))).toBe(false);
    expect(isInvoicePipelineActive(inv(2, "exception"), new Set([2]))).toBe(false);
  });

  it("returns false for settled statuses without optimistic id", () => {
    expect(isInvoicePipelineActive(inv(1, "processed"))).toBe(false);
    expect(isInvoicePipelineActive(inv(2, "exception"))).toBe(false);
  });
});

describe("uploadColumnDisplayMode", () => {
  it("shows processing for counterparty when pending and no vendor", () => {
    expect(uploadColumnDisplayMode(inv(1, "pending"), "counterparty")).toBe("processing");
  });

  it("shows value for counterparty when vendor is set during parsing", () => {
    expect(
      uploadColumnDisplayMode(inv(1, "parsing", { vendor: "Acme Supplies" }), "counterparty")
    ).toBe("value");
  });

  it("shows empty for total on exception without total", () => {
    expect(uploadColumnDisplayMode(inv(1, "exception"), "total")).toBe("empty");
  });

  it("shows empty or value for processed without optional fields", () => {
    const mode = uploadColumnDisplayMode(inv(1, "processed"), "total");
    expect(mode === "empty" || mode === "value").toBe(true);
  });

  it("treats optimistic processingIds as active pipeline for empty columns", () => {
    expect(isInvoicePipelineActive(inv(1, "pending"), new Set([1]))).toBe(true);
    expect(
      uploadColumnDisplayMode(inv(1, "pending"), "route", {
        processingIds: new Set([1]),
      })
    ).toBe("processing");
  });
});

describe("columnHasDisplayValue", () => {
  it("detects document meta from invoice_no", () => {
    expect(columnHasDisplayValue(inv(1, "pending", { invoice_no: "INV-1" }), "documentMeta")).toBe(
      true
    );
  });

  it("detects gl account when posting not applicable", () => {
    expect(
      columnHasDisplayValue(inv(1, "mapping", { gl_posting_applicable: false }), "glAccount")
    ).toBe(true);
  });
});
