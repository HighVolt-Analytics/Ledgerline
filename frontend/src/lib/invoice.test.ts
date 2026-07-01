import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import {
  invoiceSourceKind,
  invoiceSourceLabel,
  invoiceValidationConfidence,
  invoiceVendorConfidence,
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

  it("shows vendor match when non_actionable profile has explicit VR12", () => {
    expect(
      invoiceVendorConfidence(
        {
          ...baseInvoice,
          route_target: "Purchase Management",
          document_type_code: "DT-03",
          vendor_confidence: 0,
        },
        [
          {
            code: "DT-03",
            validationProfile: "non_actionable",
            posting: "Yes",
            validationRules: [{ code: "VR12", enabled: true, severity: "block" }],
          },
        ],
      ),
    ).toBe(0);
  });
});
