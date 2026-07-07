import { describe, expect, it } from "vitest";
import {
  extractionFieldKeyError,
  formatExtractionFieldKeyInput,
  reconcileExtractionFieldsForRoute,
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
    expect(keys).not.toContain("so_reference");
  });

  it("returns sales-oriented fields for Sales Management", () => {
    const keys = standardExtractionFieldsForRoute("Sales Management");
    expect(keys).toContain("so_reference");
    expect(keys).not.toContain("po_reference");
  });

  it("falls back to Vault catalogue for unknown routes", () => {
    const keys = standardExtractionFieldsForRoute("Unknown");
    expect(keys).toEqual(["document_heading", "attachment_name"]);
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
  it("prunes incompatible standard fields when route changes", () => {
    const result = reconcileExtractionFieldsForRoute({
      extractionFields: ["vendor", "po_reference", "permit_no"],
      requiredFields: ["vendor", "po_reference"],
      nextRoute: "Sales Management",
    });
    expect(result.extractionFields).toEqual(["vendor", "permit_no"]);
    expect(result.requiredFields).toEqual(["vendor"]);
    expect(result.removedStandardFields).toEqual(["po_reference"]);
  });

  it("keeps custom fields when route changes", () => {
    const result = reconcileExtractionFieldsForRoute({
      extractionFields: ["contract_party", "po_reference"],
      requiredFields: [],
      nextRoute: "Sales Management",
    });
    expect(result.extractionFields).toEqual(["contract_party"]);
    expect(result.requiredFields).toEqual([]);
    expect(result.removedStandardFields).toEqual(["po_reference"]);
  });
});
