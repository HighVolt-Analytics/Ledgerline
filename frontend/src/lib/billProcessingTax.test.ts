import { describe, expect, it } from "vitest";

import { resolveBillProcessingTaxSource } from "@/lib/billProcessingTax";

describe("resolveBillProcessingTaxSource", () => {
  it("returns none when no bill-processing platform is connected", () => {
    expect(resolveBillProcessingTaxSource({ source: "none", xero_connected: false })).toEqual({
      kind: "none",
    });
    expect(resolveBillProcessingTaxSource(undefined)).toEqual({ kind: "none" });
  });

  it("resolves the Xero adapter from source, flag, or provider", () => {
    expect(resolveBillProcessingTaxSource({ source: "xero", xero_connected: true })).toEqual({
      kind: "adapter",
      adapterId: "xero",
    });
    expect(
      resolveBillProcessingTaxSource({
        provider: { id: "xero", name: "Xero", connected: true },
      })
    ).toEqual({ kind: "adapter", adapterId: "xero" });
  });

  it("resolves the QuickBooks adapter from source or provider", () => {
    expect(
      resolveBillProcessingTaxSource({
        source: "quickbooks_online",
        provider: { id: "quickbooks_online", name: "QuickBooks", connected: true },
      })
    ).toEqual({ kind: "adapter", adapterId: "qbo" });
  });

  it("keeps unknown connected platforms distinct so UI can swap later", () => {
    expect(
      resolveBillProcessingTaxSource({
        source: "myob",
        provider: { id: "myob", name: "MYOB", connected: true },
      })
    ).toEqual({
      kind: "unsupported",
      providerId: "myob",
      providerName: "MYOB",
    });
  });
});
