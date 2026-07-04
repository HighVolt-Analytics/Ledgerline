import { describe, expect, it } from "vitest";
import { absentFieldsFromExcludeRules } from "@/lib/documentMatchRules";

describe("absentFieldsFromExcludeRules", () => {
  it("maps has_invoice_no is true to invoice_no", () => {
    expect(
      absentFieldsFromExcludeRules([
        { field: "has_invoice_no", operator: "equals", value: "true" },
      ])
    ).toEqual(["invoice_no"]);
  });

  it("maps multiple Has field checks", () => {
    expect(
      absentFieldsFromExcludeRules([
        { field: "has_total", operator: "equals", value: "true" },
        { field: "has_gst", operator: "equals", value: "true" },
      ])
    ).toEqual(["gst", "total"]);
  });

  it("ignores text exclude rules", () => {
    expect(
      absentFieldsFromExcludeRules([
        { field: "document_heading", operator: "contains", value: "Tax Invoice" },
      ])
    ).toEqual([]);
  });

  it("keeps only field keys from mixed rules", () => {
    expect(
      absentFieldsFromExcludeRules([
        { field: "document_heading", operator: "contains", value: "Tax Invoice" },
        { field: "has_invoice_no", operator: "equals", value: "true" },
        { field: "has_total", operator: "equals", value: "true" },
      ])
    ).toEqual(["invoice_no", "total"]);
  });

  it("ignores heading presence flags", () => {
    expect(
      absentFieldsFromExcludeRules([
        { field: "has_heading_invoice", operator: "equals", value: "true" },
        { field: "has_invoice_no", operator: "equals", value: "true" },
      ])
    ).toEqual(["invoice_no"]);
  });

  it("ignores presence checks when value is not true", () => {
    expect(
      absentFieldsFromExcludeRules([
        { field: "has_invoice_no", operator: "equals", value: "false" },
      ])
    ).toEqual([]);
  });
});
