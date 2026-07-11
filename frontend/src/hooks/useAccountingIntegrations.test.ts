/**
 * @vitest-environment happy-dom
 */
import { describe, expect, it } from "vitest";

import {
  parseLedgerLinkInvoiceId,
  xeroIntegrationKeys,
} from "@/hooks/useAccountingIntegrations";

describe("useAccountingIntegrations helpers", () => {
  it("defines distinct tenant-scoped key parts per Xero resource", () => {
    expect(xeroIntegrationKeys.readiness).toEqual(["integrations", "xero", "readiness"]);
    expect(xeroIntegrationKeys.connections).toEqual(["integrations", "xero", "connections"]);
    expect(xeroIntegrationKeys.status).toEqual(["integrations", "accounting", "status"]);
    expect(xeroIntegrationKeys.readiness).not.toEqual(xeroIntegrationKeys.connections);
  });

  it("parses invoice ids from ledger-link export row ids", () => {
    expect(parseLedgerLinkInvoiceId("ll-inv-123")).toBe(123);
    expect(parseLedgerLinkInvoiceId("ll-pay-9")).toBeNull();
    expect(parseLedgerLinkInvoiceId("invalid")).toBeNull();
  });
});
