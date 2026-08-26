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
  effectiveEvaluationStatus,
  evaluationReviewTooltip,
  evaluationStatusDescription,
  evaluationStatusLabel,
  invoiceCounterpartyConfidence,
  invoiceMatchesCaptureChannel,
  invoiceSourceKind,
  invoiceSourceLabel,
  invoiceValidationConfidence,
  invoiceVendorConfidence,
  vendorMatchApplicable,
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

describe("effectiveEvaluationStatus", () => {
  it("normalizes stale needs_review after successful posting", () => {
    expect(
      effectiveEvaluationStatus({
        status: "processed",
        evaluation_status: "needs_review",
      }),
    ).toBe("auto_coded");
  });

  it("preserves review while posting is incomplete", () => {
    expect(
      effectiveEvaluationStatus({
        status: "exception",
        evaluation_status: "needs_review",
      }),
    ).toBe("needs_review");
  });

  it("surfaces exception auto_coded as needs review", () => {
    expect(
      effectiveEvaluationStatus({
        status: "exception",
        evaluation_status: "auto_coded",
      }),
    ).toBe("needs_review");
  });
});

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

  it("keeps explicit upload when claimant/sender is set", () => {
    expect(
      invoiceSourceKind({
        capture_source: "upload",
        email_sender: "priya@acme-hospitality.com.au",
        connected_mailbox_id: null,
      } as Invoice),
    ).toBe("upload");
    expect(
      invoiceMatchesCaptureChannel(
        {
          capture_source: "upload",
          email_sender: "priya@acme-hospitality.com.au",
          connected_mailbox_id: null,
        } as Invoice,
        "upload",
      ),
    ).toBe(true);
    expect(
      invoiceMatchesCaptureChannel(
        {
          capture_source: "email",
          connected_mailbox_id: 1,
        } as Invoice,
        "all",
      ),
    ).toBe(true);
    expect(
      invoiceMatchesCaptureChannel(
        {
          capture_source: "upload",
          email_sender: "priya@acme-hospitality.com.au",
          connected_mailbox_id: null,
        } as Invoice,
        "email",
      ),
    ).toBe(false);
  });

  it("uses mailbox connection for legacy email rows without capture_source", () => {
    expect(
      invoiceSourceKind({
        capture_source: null,
        email_sender: "vendor@example.com",
        connected_mailbox_id: 3,
      } as Invoice),
    ).toBe("email");
    expect(
      invoiceSourceKind({
        capture_source: null,
        email_sender: "claimant@example.com",
        connected_mailbox_id: null,
      } as Invoice),
    ).toBe("upload");
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
        route_target: ROUTE_PURCHASE,
        purchase_document_type: "grn",
        vendor: "Sysco Australia Pty Ltd",
        extracted_fields: {
          seller_name: "GRN-2026-0001",
        },
      } as Invoice),
    ).toBe("Sysco Australia Pty Ltd");
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

  it("shows customer match label and confidence on sales route", () => {
    expect(
      counterpartyMatchLabel({
        ...baseInvoice,
        route_target: ROUTE_SALES,
        document_type_code: "DT-28",
      }),
    ).toBe("Customer match");
    expect(
      invoiceCounterpartyConfidence({
        ...baseInvoice,
        route_target: ROUTE_SALES,
        vendor_confidence: 88,
      }),
    ).toBe(88);
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

  it("does not treat sales pending_vendor as vendor match", () => {
    expect(
      vendorMatchApplicable({
        ...baseInvoice,
        route_target: ROUTE_SALES,
        evaluation_status: "pending_vendor",
      }),
    ).toBe(false);
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

describe("evaluationReviewTooltip", () => {
  it("points to failed validation rules in the audit tab", () => {
    expect(
      evaluationReviewTooltip({
        evaluation_status: "needs_review",
        validation_results: [
          { rule: "VR03", passed: false, message: "GST does not reconcile", skipped: false },
        ],
        status: "exception",
      } as Invoice),
    ).toBe("Audit tab — VR03 — GST does not reconcile");
  });

  it("points to classification when document type is missing", () => {
    expect(
      evaluationReviewTooltip({
        evaluation_status: "needs_review",
        validation_results: null,
        document_type_code: null,
        llm_suggested_dt: "DT-11",
        route_target: "Purchase Management",
        status: "exception",
      } as Invoice),
    ).toBe("Fields tab — confirm document type (DT-11)");
  });

  it("points to GL mapping for suspense accounts", () => {
    expect(
      evaluationReviewTooltip({
        evaluation_status: "needs_review",
        validation_results: null,
        document_type_code: "DT-11",
        route_target: "Purchase Management",
        account_code: "9999",
        account_name: "Suspense",
        gl_posting_applicable: true,
        status: "exception",
      } as Invoice),
    ).toBe("Lines tab — assign a GL account or clear suspense mapping");
  });

  it("maps review reason codes to readable labels", () => {
    expect(
      evaluationReviewTooltip({ evaluation_status: "needs_review" } as Invoice, ["LLM_LOW_CONF"]),
    ).toBe("LLM confidence below auto-route threshold");
  });

  it("prefers API resolution_hint when present", () => {
    expect(
      evaluationReviewTooltip({
        evaluation_status: "needs_review",
        validation_results: [
          { rule: "VR03", passed: false, message: "GST does not reconcile", skipped: false },
        ],
        resolution_hint: "Audit tab — reconciliation blocked posting",
        status: "exception",
      } as Invoice),
    ).toBe("Audit tab — reconciliation blocked posting");
  });

  it("uses ungrounded-amount copy for vision_header_review when flagged", () => {
    expect(
      evaluationReviewTooltip({
        evaluation_status: "vision_header_review",
        extracted_fields: { amount_ungrounded: "true" },
        status: "exception",
      } as Invoice),
    ).toBe("Fields tab — Amount could not be verified against document text");
  });

  it("uses amount-inconsistency copy for vision_header_review when flagged", () => {
    expect(
      evaluationReviewTooltip({
        evaluation_status: "vision_header_review",
        extracted_fields: { amount_inconsistency: "true" },
        status: "exception",
      } as Invoice),
    ).toBe("Fields tab — Amounts do not add up");
  });
});

describe("evaluationStatusLabel", () => {
  it("shows pending customer on sales route", () => {
    expect(evaluationStatusLabel("pending_vendor", ROUTE_SALES)).toBe("Pending customer");
    expect(evaluationStatusLabel("pending_vendor", ROUTE_PURCHASE)).toBe("Pending vendor");
  });

  it("keeps awaiting classification as status label", () => {
    expect(evaluationStatusLabel("awaiting_classification")).toBe("Awaiting classification");
  });

  it("shows dedicated understood-path evaluation tags", () => {
    expect(evaluationStatusLabel("vision_vaulted")).toBe("Filed — not reviewed");
    expect(evaluationStatusLabel("vision_header_review")).toBe("Vision header review");
  });
});

describe("evaluationStatusDescription", () => {
  it("points sales holds to customer masters", () => {
    expect(evaluationStatusDescription("pending_vendor", ROUTE_SALES)).toContain("Customers");
    expect(evaluationStatusDescription("pending_vendor", ROUTE_PURCHASE)).toContain("Vendors");
  });

  it("marks vision_vaulted as system-filed, not human-approved", () => {
    expect(evaluationStatusDescription("vision_vaulted")).toMatch(/never human-confirmed/i);
    expect(evaluationStatusDescription("auto_coded")).not.toMatch(/never human-confirmed/i);
  });
});
