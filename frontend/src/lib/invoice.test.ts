import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import {
  glPostingApplicable,
  counterpartyColumnLabel,
  counterpartyKind,
  counterpartyLabel,
  counterpartyLabelForRoute,
  counterpartyMatchColumnLabel,
  counterpartyMatchLabel,
  counterpartyName,
  counterpartyUnknownLabel,
  invoiceCounterpartyConfidence,
  invoiceSourceKind,
  invoiceSourceLabel,
  invoiceValidationConfidence,
  invoiceVendorConfidence,
  ROUTE_PURCHASE,
  ROUTE_SALES,
  validationPassApplicable,
} from "@/lib/invoice";
const baseInvoice = {
  id: 1,
  currency: "AUD",
  status: "processed",
  validation_results: [{ rule: "VR03", passed: false, message: "fail", skipped: false }],
} as Invoice;

describe("validationPassApplicable", () => {
  it("returns false for vault route", () => {
    expect(
      validationPassApplicable({
        ...baseInvoice,
        route_target: "Vault",
        document_type_code: "DT-02",
      }),
    ).toBe(false);
  });

  it("returns false for non_actionable document types", () => {
    expect(
      validationPassApplicable(
        {
          ...baseInvoice,
          route_target: "Purchase Management",
          document_type_code: "DT-02",
        },
        [{ code: "DT-02", validationProfile: "non_actionable", posting: "No" }],
      ),
    ).toBe(false);
  });
});

describe("invoiceValidationConfidence", () => {
  it("returns null when validation pass does not apply", () => {
    expect(
      invoiceValidationConfidence(
        {
          ...baseInvoice,
          route_target: "Vault",
          document_type_code: "DT-13",
        },
        [{ code: "DT-13", validationProfile: "non_actionable", posting: "No" }],
      ),
    ).toBeNull();
  });

  it("returns pass rate for payable invoices", () => {
    expect(
      invoiceValidationConfidence(
        {
          ...baseInvoice,
          route_target: "Purchase Management",
          document_type_code: "DT-01",
          validation_pass_rate: 50,
          validation_results: [
            { rule: "VR01", passed: true, message: "ok", skipped: false },
            { rule: "VR03", passed: false, message: "fail", skipped: false },
          ],
        },
        [{ code: "DT-01", validationProfile: "standard", posting: "Yes" }],
      ),
    ).toBe(50);
  });
});

describe("invoiceSourceKind", () => {
  it("uses capture_source instead of storage path", () => {
    expect(
      invoiceSourceKind({
        capture_source: "upload",
        storage_vendor_slug: "spectra-innovations",
        email_sender: null,
        connected_mailbox_id: null,
      } as Invoice),
    ).toBe("upload");
    expect(invoiceSourceLabel("upload")).toBe("Direct upload");
  });
});

describe("counterparty labels", () => {
  it("maps finance books to vendor vs customer", () => {
    expect(counterpartyKind({ route_target: ROUTE_PURCHASE } as Invoice)).toBe("vendor");
    expect(counterpartyLabel({ route_target: ROUTE_PURCHASE } as Invoice)).toBe("Vendor");
    expect(counterpartyLabel({ route_target: ROUTE_SALES } as Invoice)).toBe("Customer");
    expect(counterpartyLabel({ route_target: "Team Expenses" } as Invoice)).toBe("Employee");
    expect(counterpartyLabel({ route_target: "Vault" } as Invoice)).toBe("Counterparty");
    expect(counterpartyLabelForRoute(ROUTE_SALES)).toBe("Customer");
  });

  it("uses mixed inbox column labels", () => {
    expect(counterpartyColumnLabel({ mixed: true })).toBe("Counterparty");
    expect(counterpartyMatchColumnLabel({ mixed: true })).toBe("Master match");
    expect(counterpartyColumnLabel({ routeTarget: ROUTE_SALES })).toBe("Customer");
    expect(counterpartyMatchColumnLabel({ routeTarget: ROUTE_PURCHASE })).toBe("Vendor match");
  });

  it("formats counterparty display values", () => {
    expect(counterpartyName({ vendor: " Acme " } as Invoice)).toBe("Acme");
    expect(
      counterpartyName({
        route_target: ROUTE_SALES,
        vendor: "Tenant Org",
        extracted_fields: {
          buyer_name: "Harbour View Hotel",
          seller_name: "Tenant Org",
        },
      } as Invoice),
    ).toBe("Harbour View Hotel");
    expect(counterpartyUnknownLabel({ route_target: ROUTE_SALES } as Invoice)).toBe(
      "Unknown customer",
    );
  });

  it("hides master match on sales until customer scoring exists", () => {
    expect(
      counterpartyMatchLabel({
        ...baseInvoice,
        route_target: ROUTE_SALES,
        document_type_code: "DT-28",
      }),
    ).toBeNull();
    expect(
      invoiceCounterpartyConfidence({
        ...baseInvoice,
        route_target: ROUTE_SALES,
        vendor_confidence: 88,
      }),
    ).toBeNull();
  });
});

describe("invoiceVendorConfidence", () => {
  it("returns null for vault documents", () => {
    expect(
      invoiceVendorConfidence(
        {
          ...baseInvoice,
          route_target: "Vault",
          document_type_code: "DT-02",
          vendor_confidence: 90,
        },
        [{ code: "DT-02", validationProfile: "non_actionable", posting: "No" }],
      ),
    ).toBeNull();
  });

  it("shows 0% for pending vendor when confidence is missing", () => {
    expect(
      invoiceVendorConfidence(
        {
          ...baseInvoice,
          route_target: "Purchase Management",
          document_type_code: "DT-01",
          evaluation_status: "pending_vendor",
          vendor_confidence: null,
        },
        [{ code: "DT-01", validationProfile: "standard", posting: "Yes" }],
      ),
    ).toBe(0);
  });

  it("shows vendor confidence on payable routes with VR12", () => {
    expect(
      invoiceVendorConfidence(
        {
          ...baseInvoice,
          route_target: "Purchase Management",
          document_type_code: "DT-01",
          vendor_confidence: 42,
        },
        [{ code: "DT-01", validationProfile: "standard", posting: "Yes" }],
      ),
    ).toBe(42);
  });
});

describe("glPostingApplicable", () => {
  it("returns API flag when present", () => {
    expect(
      glPostingApplicable({
        ...baseInvoice,
        gl_posting_applicable: false,
      } as Invoice),
    ).toBe(false);
  });

  it("returns false for PO supporting docs", () => {
    expect(
      glPostingApplicable({
        ...baseInvoice,
        route_target: "Purchase Management",
        purchase_document_type: "po",
      } as Invoice),
    ).toBe(false);
  });
});
