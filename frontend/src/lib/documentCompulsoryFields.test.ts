import { describe, expect, it } from "vitest";
import {
  ensureExtractionSuperset,
  normalizeCompulsoryFields,
  optionalExtractionFields,
  validateCompulsoryFieldsForApproval,
} from "@/lib/documentCompulsoryFields";

describe("normalizeCompulsoryFields", () => {
  it("clamps compulsory to extraction superset", () => {
    expect(
      normalizeCompulsoryFields(["total", "missing"], ["vendor", "total"])
    ).toEqual(["total"]);
  });

  it("keeps compulsory empty when none starred", () => {
    expect(normalizeCompulsoryFields([], ["vendor", "total"])).toEqual([]);
  });

  it("drops infrastructure keys from compulsory", () => {
    expect(
      normalizeCompulsoryFields(
        ["attachment_name", "document_text", "permit_no"],
        ["attachment_name", "document_text", "permit_no", "vendor"]
      )
    ).toEqual(["permit_no"]);
  });

  it("supports starring a subset without forcing all extraction fields", () => {
    const extraction = ["vendor", "total", "invoice_no"];
    expect(normalizeCompulsoryFields(["vendor"], extraction)).toEqual(["vendor"]);
    expect(normalizeCompulsoryFields([], extraction)).toEqual([]);
    expect(normalizeCompulsoryFields(["vendor", "total"], extraction)).toEqual([
      "vendor",
      "total",
    ]);
  });
});

describe("ensureExtractionSuperset", () => {
  it("adds compulsory keys to extraction list", () => {
    expect(ensureExtractionSuperset(["po_reference"], ["vendor"])).toEqual([
      "vendor",
      "po_reference",
    ]);
  });
});

describe("optionalExtractionFields", () => {
  it("returns extraction minus compulsory", () => {
    expect(
      optionalExtractionFields(["vendor", "total", "invoice_no"], ["vendor", "total"])
    ).toEqual(["invoice_no"]);
  });
});

describe("validateCompulsoryFieldsForApproval", () => {
  it("reports missing compulsory keys", () => {
    const result = validateCompulsoryFieldsForApproval(
      { vendor: "Acme", total: "10" },
      ["vendor", "total", "due_date"]
    );
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.message).toContain("due_date");
    }
  });
});
