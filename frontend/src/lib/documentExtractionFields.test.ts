import { describe, expect, it } from "vitest";
import {
  customFieldLinkingConflictError,
  extractionFieldKeyError,
  formatExtractionFieldKeyInput,
  linkingStandardFieldForCustomAlias,
  mergeRouteCompulsoryIntoConfig,
  missingRouteRecommendations,
  reconcileExtractionFieldsForRoute,
  routeCompulsoryBaseline,
  sanitizeExtractionFieldKey,
  splitExtractionFields,
  standardExtractionFieldsForRoute,
} from "@/lib/documentExtractionFields";

describe("formatExtractionFieldKeyInput", () => {
  it("lowercases uppercase input", () => {
    expect(formatExtractionFieldKeyInput("CONTRACT_PARTY")).toBe("contract_party");
  });

  it("converts spaces to underscores", () => {
    expect(formatExtractionFieldKeyInput("Contract Party")).toBe("contract_party");
    expect(formatExtractionFieldKeyInput("contract party")).toBe("contract_party");
  });

  it("converts hyphens to underscores", () => {
    expect(formatExtractionFieldKeyInput("contract-party")).toBe("contract_party");
  });

  it("strips leading digits", () => {
    expect(formatExtractionFieldKeyInput("123foo")).toBe("foo");
  });

  it("strips invalid characters", () => {
    expect(formatExtractionFieldKeyInput("bad-key!")).toBe("bad_key");
  });

  it("returns empty for underscore-only input", () => {
    expect(formatExtractionFieldKeyInput("_")).toBe("");
    expect(formatExtractionFieldKeyInput("___")).toBe("");
  });

  it("returns empty for empty input", () => {
    expect(formatExtractionFieldKeyInput("")).toBe("");
    expect(formatExtractionFieldKeyInput("   ")).toBe("");
  });
});

describe("sanitizeExtractionFieldKey", () => {
  it("accepts valid formatted keys", () => {
    expect(sanitizeExtractionFieldKey("CONTRACT_PARTY")).toBe("contract_party");
    expect(sanitizeExtractionFieldKey("Contract Party")).toBe("contract_party");
    expect(sanitizeExtractionFieldKey("contract-party")).toBe("contract_party");
    expect(sanitizeExtractionFieldKey("bad-key!")).toBe("bad_key");
  });

  it("rejects empty or invalid keys", () => {
    expect(sanitizeExtractionFieldKey("")).toBeNull();
    expect(sanitizeExtractionFieldKey("_")).toBeNull();
    expect(sanitizeExtractionFieldKey("123")).toBeNull();
  });
});

describe("extractionFieldKeyError", () => {
  it("returns null for valid keys", () => {
    expect(extractionFieldKeyError("contract_party")).toBeNull();
    expect(extractionFieldKeyError("CONTRACT_PARTY")).toBeNull();
  });

  it("returns helpful errors for invalid input", () => {
    expect(extractionFieldKeyError("")).toMatch(/enter a field name/i);
    expect(extractionFieldKeyError("123")).toMatch(/start with a letter/i);
    expect(extractionFieldKeyError("_")).toMatch(/start with a letter/i);
  });
});

describe("standardExtractionFieldsForRoute", () => {
  it("returns purchase-oriented fields for Purchase Management", () => {
    const keys = standardExtractionFieldsForRoute("Purchase Management");
    expect(keys).toContain("po_reference");
    expect(keys).toContain("invoice_no");
    expect(keys).toContain("so_reference");
  });

  it("returns sales-oriented fields for Sales Management", () => {
    const keys = standardExtractionFieldsForRoute("Sales Management");
    expect(keys).toContain("so_reference");
    expect(keys).toContain("invoice_no");
    expect(keys).toContain("po_reference");
  });

  it("always includes linking fields on every route", () => {
    for (const route of [
      "Purchase Management",
      "Sales Management",
      "Expenses Management",
      "Team Expenses",
      "Vault",
    ] as const) {
      const keys = standardExtractionFieldsForRoute(route);
      expect(keys).toEqual(
        expect.arrayContaining([
          "invoice_no",
          "proforma_invoice_no",
          "po_reference",
          "so_reference",
        ])
      );
    }
  });

  it("falls back to Vault catalogue for unknown routes", () => {
    const keys = standardExtractionFieldsForRoute("Unknown");
    expect(keys).toEqual([
      "document_heading",
      "attachment_name",
      "vendor",
      "invoice_no",
      "invoice_date",
      "proforma_invoice_no",
      "po_reference",
      "so_reference",
    ]);
  });

  it("offers vendor and invoice date for Vault filing folders", () => {
    const keys = standardExtractionFieldsForRoute("Vault");
    expect(keys).toEqual(
      expect.arrayContaining(["vendor", "invoice_date", "invoice_no", "document_heading"])
    );
  });
});

describe("customFieldLinkingConflictError", () => {
  it("redirects invoice/po/so aliases to standard linking fields", () => {
    expect(customFieldLinkingConflictError("invoice_number")).toMatch(/invoice number/i);
    expect(linkingStandardFieldForCustomAlias("invoice_number")).toBe("invoice_no");
    expect(linkingStandardFieldForCustomAlias("proforma_no")).toBe("proforma_invoice_no");
    expect(linkingStandardFieldForCustomAlias("po_number")).toBe("po_reference");
    expect(linkingStandardFieldForCustomAlias("so_number")).toBe("so_reference");
  });

  it("blocks ambiguous reference custom keys", () => {
    expect(customFieldLinkingConflictError("reference_no")).toMatch(/bundling/i);
  });

  it("allows unrelated custom keys", () => {
    expect(customFieldLinkingConflictError("contract_party")).toBeNull();
  });
});

describe("splitExtractionFields", () => {
  it("separates standard presets from custom keys", () => {
    const { standard, custom } = splitExtractionFields([
      "vendor",
      "permit_no",
      "document_text",
    ]);
    expect(standard).toEqual(["vendor"]);
    expect(custom).toEqual(["permit_no", "document_text"]);
  });
});

describe("reconcileExtractionFieldsForRoute", () => {
  it("keeps linking standard fields when route changes", () => {
    const result = reconcileExtractionFieldsForRoute({
      extractionFields: ["vendor", "po_reference", "permit_no"],
      requiredFields: ["vendor", "po_reference"],
      nextRoute: "Sales Management",
    });
    expect(result.extractionFields).toEqual(["vendor", "po_reference", "permit_no"]);
    expect(result.requiredFields).toEqual(["vendor", "po_reference"]);
    expect(result.removedStandardFields).toEqual([]);
  });

  it("keeps custom fields when route changes", () => {
    const result = reconcileExtractionFieldsForRoute({
      extractionFields: ["contract_party", "po_reference"],
      requiredFields: [],
      nextRoute: "Sales Management",
    });
    expect(result.extractionFields).toEqual(["po_reference", "contract_party"]);
    expect(result.requiredFields).toEqual([]);
    expect(result.removedStandardFields).toEqual([]);
  });

  it("still prunes non-linking route-specific fields", () => {
    const result = reconcileExtractionFieldsForRoute({
      extractionFields: ["vendor", "seller_name", "permit_no"],
      requiredFields: ["vendor", "seller_name"],
      nextRoute: "Purchase Management",
    });
    expect(result.extractionFields).toEqual(["vendor", "permit_no"]);
    expect(result.requiredFields).toEqual(["vendor"]);
    expect(result.removedStandardFields).toEqual(["seller_name"]);
  });
});

describe("routeCompulsoryBaseline", () => {
  it("returns team money fields", () => {
    expect(routeCompulsoryBaseline("Team Expenses")).toEqual([
      "email_sender",
      "subtotal",
      "gst",
      "total",
    ]);
  });

  it("returns purchase baseline with subtotal and gst", () => {
    expect(routeCompulsoryBaseline("Sales Management")).toEqual([
      "vendor",
      "subtotal",
      "gst",
      "total",
      "due_date",
    ]);
  });

  it("returns empty for vault", () => {
    expect(routeCompulsoryBaseline("Vault")).toEqual([]);
  });
});

describe("missingRouteRecommendations", () => {
  it("lists route keys not yet starred", () => {
    expect(
      missingRouteRecommendations({
        routeTarget: "Purchase Management",
        requiredFields: ["vendor"],
        extractionFields: ["vendor", "subtotal", "gst", "total", "due_date"],
        transactional: true,
      })
    ).toEqual(["subtotal", "gst", "total", "due_date"]);
  });
});

describe("mergeRouteCompulsoryIntoConfig", () => {
  it("does not merge baseline for non-transactional drafts", () => {
    const result = mergeRouteCompulsoryIntoConfig({
      requiredFields: ["permit_no"],
      extractionFields: ["vendor", "permit_no"],
      routeTarget: "Purchase Management",
      transactional: false,
    });
    expect(result.requiredFields).toEqual(["permit_no"]);
  });
});
