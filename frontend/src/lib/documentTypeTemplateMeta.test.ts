import { describe, expect, it } from "vitest";
import { orgTitleDivergesFromShippedTemplate } from "@/lib/documentTypeTemplateMeta";

const SHIPPED = [
  { code: "DT-13", title: "Vendor statement", shortTitle: "Vendor statement" },
];

describe("orgTitleDivergesFromShippedTemplate", () => {
  it("flags repurposed packing list title", () => {
    expect(
      orgTitleDivergesFromShippedTemplate("DT-13", "PACKING LIST", "PACKING LIST", SHIPPED),
    ).toBe(true);
  });

  it("passes when title matches shipped template", () => {
    expect(
      orgTitleDivergesFromShippedTemplate(
        "DT-13",
        "Vendor statement",
        "Vendor statement",
        SHIPPED,
      ),
    ).toBe(false);
  });
});
