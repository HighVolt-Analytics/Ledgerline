import { describe, expect, it } from "vitest";
import type { ReconciliationOverview } from "@/api/types";
import { mapReconciliationOverview } from "@/lib/reconciliation";

describe("mapReconciliationOverview currency", () => {
  it("preserves per-invoice currency and mixed-currency flags", () => {
    const data: ReconciliationOverview = {
      sum_totals: "299.00",
      sum_dr: "299.00",
      sum_cr: "299.00",
      delta_dr_cr: "0.00",
      balanced: true,
      base_currency: "AUD",
      has_mixed_currencies: true,
      totals_by_currency: { AUD: "299.00", INR: "9800.53" },
      dr_by_currency: { AUD: "299.00", INR: "9800.53" },
      cr_by_currency: { AUD: "299.00", INR: "9800.53" },
      by_date: [
        {
          date: "2026-05-02",
          count: 2,
          sum_dr: "0",
          sum_cr: "0",
          delta: "0",
          has_mixed_currencies: true,
          currencies: ["AUD", "INR"],
          totals_by_currency: { AUD: "299.00", INR: "9800.53" },
          dr_by_currency: { AUD: "299.00", INR: "9800.53" },
          cr_by_currency: { AUD: "299.00", INR: "9800.53" },
          invoices: [
            {
              id: "DOC-7",
              invoice_id: 7,
              vendor: "BrightDesk",
              total: "299.00",
              currency: "AUD",
              postings: [],
            },
            {
              id: "DOC-85",
              invoice_id: 85,
              vendor: "MAKEMYTRIP",
              total: "9800.53",
              currency: "INR",
              postings: [],
            },
          ],
        },
      ],
    };

    const recon = mapReconciliationOverview(data);
    expect(recon.hasMixedCurrencies).toBe(true);
    expect(recon.totalsByCurrency.AUD).toBe(299);
    expect(recon.totalsByCurrency.INR).toBe(9800.53);
    expect(recon.byDate[0].invoices[1].currency).toBe("INR");
    expect(recon.byDate[0].invoices[0].invoiceId).toBe(7);
    expect(recon.byDate[0].invoices[1].invoiceId).toBe(85);
  });
});
