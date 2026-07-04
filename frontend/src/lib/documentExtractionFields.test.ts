import { describe, expect, it } from "vitest";
import {
  extractionFieldKeyError,
  formatExtractionFieldKeyInput,
  sanitizeExtractionFieldKey,
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
