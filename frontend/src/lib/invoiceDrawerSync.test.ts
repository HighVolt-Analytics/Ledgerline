import { describe, expect, it } from "vitest";
import { shouldApplyDrawerInvoiceUpdate } from "@/lib/invoiceDrawerSync";

describe("shouldApplyDrawerInvoiceUpdate", () => {
  it("applies updates only while the drawer is still showing that invoice", () => {
    expect(
      shouldApplyDrawerInvoiceUpdate({
        open: true,
        activeInvoiceId: 10,
        updatedId: 10,
      })
    ).toBe(true);
  });

  it("blocks a processing invoice from overwriting another open drawer", () => {
    expect(
      shouldApplyDrawerInvoiceUpdate({
        open: true,
        activeInvoiceId: 20,
        updatedId: 10,
      })
    ).toBe(false);
  });

  it("blocks updates after the drawer is closed", () => {
    expect(
      shouldApplyDrawerInvoiceUpdate({
        open: false,
        activeInvoiceId: 10,
        updatedId: 10,
      })
    ).toBe(false);
  });
});
