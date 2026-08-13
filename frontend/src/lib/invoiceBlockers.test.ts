import { describe, expect, it } from "vitest";
import { detectInvoiceBlockers } from "@/lib/invoiceBlockers";

describe("detectInvoiceBlockers", () => {
  it("does not flag vendor when the DT extraction list omits vendor", () => {
    const blockers = detectInvoiceBlockers({
      currency: "MMK",
      total: "340000",
      vendor: null,
      evaluation_status: "vision_header_review",
      document_type_extraction_fields: ["total", "currency", "invoice_date", "employee_name"],
    });
    expect(blockers).toEqual([]);
  });

  it("still flags vendor when the DT extracts vendor", () => {
    const blockers = detectInvoiceBlockers({
      currency: "AUD",
      total: "100",
      vendor: "",
      evaluation_status: "vision_header_review",
      document_type_extraction_fields: ["vendor", "total"],
    });
    expect(blockers).toEqual(["vendor"]);
  });

  it("does not invent vendor/total/currency when the DT lists no extraction fields", () => {
    const blockers = detectInvoiceBlockers({
      currency: "",
      total: null,
      vendor: null,
      evaluation_status: "vision_header_review",
      document_type_extraction_fields: [],
    });
    expect(blockers).toEqual([]);
  });
});
