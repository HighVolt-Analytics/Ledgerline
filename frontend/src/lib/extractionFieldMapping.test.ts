import { describe, expect, it } from "vitest";
import { isPresetExtractionFieldKey } from "@/lib/documentExtractionFields";
import {
  remapBankDetailsForDictionaryCode,
  remapTaxIdForDictionaryCode,
  remapTier2DraftKey,
  resolvedExtractionFieldsFromMapping,
  unresolvedExtractionHintsFromMapping,
} from "@/lib/extractionFieldMapping";
import mappingFile from "@/lib/extraction_field_mapping.json";

describe("extraction_field_mapping.json merge", () => {
  it("covers all 90 dictionary codes", () => {
    expect(mappingFile.entries).toHaveLength(90);
  });

  it("resolves only catalogue keys for every entry", () => {
    for (const entry of mappingFile.entries) {
      const keys = resolvedExtractionFieldsFromMapping(entry.code);
      for (const key of keys) {
        expect(isPresetExtractionFieldKey(key), `${entry.code}:${key}`).toBe(true);
      }
    }
  });

  it("keeps LIB-069 unresolved phrases as hints only", () => {
    expect(resolvedExtractionFieldsFromMapping("LIB-069")).toEqual([]);
    expect(unresolvedExtractionHintsFromMapping("LIB-069").length).toBeGreaterThan(0);
  });

  it("remaps Tier2 aliases to catalogue names", () => {
    const keys = resolvedExtractionFieldsFromMapping("LIB-001");
    expect(keys).toContain("seller_tax_id");
    expect(keys).toContain("remittance_reference");
    expect(keys).toContain("service_period");
    expect(keys).not.toContain("tax_id");
    expect(keys).not.toContain("payment_reference");
  });

  it("remaps tax_id differently on vendor-side vs customer-side entries", () => {
    expect(remapTaxIdForDictionaryCode("LIB-001")).toBe("seller_tax_id");
    expect(remapTier2DraftKey("tax_id", "LIB-001")).toBe("seller_tax_id");
    expect(resolvedExtractionFieldsFromMapping("LIB-001")).toContain("seller_tax_id");
    expect(resolvedExtractionFieldsFromMapping("LIB-001")).not.toContain("buyer_tax_id");

    expect(remapTaxIdForDictionaryCode("LIB-003")).toBe("buyer_tax_id");
    expect(remapTier2DraftKey("tax_id", "LIB-003")).toBe("buyer_tax_id");
    expect(resolvedExtractionFieldsFromMapping("LIB-003")).toContain("buyer_tax_id");
    expect(resolvedExtractionFieldsFromMapping("LIB-003")).not.toContain("seller_tax_id");
  });

  it("remaps bank_details differently on vendor-side vs customer-side entries", () => {
    // LIB-001 is vendor/AP (no bank_details in its draft list — probe the remap directly).
    expect(remapBankDetailsForDictionaryCode("LIB-001")).toBe("bank_details");
    expect(remapTier2DraftKey("bank_details", "LIB-001")).toBe("bank_details");

    // LIB-016 POS Settlement is customer/Sales and drafts bank_details.
    expect(remapBankDetailsForDictionaryCode("LIB-016")).toBe("buyer_bank_details");
    expect(remapTier2DraftKey("bank_details", "LIB-016")).toBe("buyer_bank_details");
    const keys = resolvedExtractionFieldsFromMapping("LIB-016");
    expect(keys).toContain("buyer_bank_details");
    expect(keys).not.toContain("bank_details");
  });

  it("remaps customer→buyer_name and keeps a coherent AR field set on LIB-003", () => {
    const keys = resolvedExtractionFieldsFromMapping("LIB-003");
    expect(keys).toContain("buyer_name");
    expect(keys).toContain("buyer_tax_id");
    expect(keys).not.toContain("customer");
    expect(keys).not.toContain("tax_id");
    expect(keys).not.toContain("seller_tax_id");
    expect(keys).toContain("contract_reference");
    expect(keys).toContain("service_period");
    expect(keys).not.toContain("billing_milestone");
    expect(keys).not.toContain("customer_id");
  });

  it("keeps a working mid-tier AP utility field set (LIB-023)", () => {
    const keys = resolvedExtractionFieldsFromMapping("LIB-023");
    expect(keys).toEqual(
      expect.arrayContaining([
        "vendor",
        "invoice_no",
        "currency",
        "subtotal",
        "total",
        "line_items",
        "po_reference",
        "cost_centre",
        "due_date",
        "invoice_date",
        "service_period",
        "remittance_reference",
        "seller_tax_id",
      ])
    );
    expect(keys).not.toContain("meter_id");
    expect(keys).not.toContain("tariff_plan");
    expect(keys).not.toContain("usage");
    expect(unresolvedExtractionHintsFromMapping("LIB-023").some((h) => h.includes("meter_id"))).toBe(
      true
    );
  });
});
