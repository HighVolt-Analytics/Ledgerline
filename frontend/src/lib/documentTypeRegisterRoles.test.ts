import { describe, expect, it } from "vitest";
import {
  dtCodeForRegisterRole,
  purchaseRegisterRoleForDefinition,
  salesRegisterRoleForDefinition,
} from "@/lib/documentTypeRegisterRoles";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

function dt(partial: Partial<DocumentTypeDefinition> & { code: string; title: string }): DocumentTypeDefinition {
  return {
    shortTitle: partial.title,
    enabled: true,
    klass: "Transactional",
    posting: "Yes",
    routeTarget: "Purchase Management",
    playbookProfile: "",
    purchaseBundleRole: "",
    salesBundleRole: "",
    classifier: {
      priority: 10,
      enabled: true,
      confidence: 0.8,
      root: { type: "group", operator: "AND", children: [] },
    },
    ...partial,
  } as DocumentTypeDefinition;
}

describe("documentTypeRegisterRoles", () => {
  it("resolves purchase commercial from org po_goods, not template DT-01 first", () => {
    const catalog = [
      dt({
        code: "DT-05",
        title: "PO copy",
        posting: "No",
        purchaseBundleRole: "po",
        playbookProfile: "supporting",
      }),
      dt({
        code: "DT-06",
        title: "GRN",
        posting: "No",
        purchaseBundleRole: "grn",
        playbookProfile: "supporting",
      }),
      dt({ code: "DT-88", title: "Harbour AP invoice", playbookProfile: "po_goods" }),
      dt({ code: "DT-01", title: "Commercial invoice", playbookProfile: "po_goods" }),
    ];
    expect(purchaseRegisterRoleForDefinition(catalog[2])).toBe("invoice");
    expect(dtCodeForRegisterRole({ side: "purchase", role: "invoice", documentTypes: catalog }).code).toBe(
      "DT-88"
    );
    expect(dtCodeForRegisterRole({ side: "purchase", role: "po", documentTypes: catalog }).code).toBe(
      "DT-05"
    );
  });

  it("resolves sales commercial from org ar_goods", () => {
    const catalog = [
      dt({
        code: "DT-99",
        title: "Customer tax invoice",
        routeTarget: "Sales Management",
        playbookProfile: "ar_goods",
      }),
    ];
    expect(salesRegisterRoleForDefinition(catalog[0])).toBe("invoice");
    expect(dtCodeForRegisterRole({ side: "sales", role: "invoice", documentTypes: catalog }).code).toBe(
      "DT-99"
    );
  });

  it("uses shipped DT-02/03/01 as last-resort purchase fallbacks", () => {
    expect(dtCodeForRegisterRole({ side: "purchase", role: "po", documentTypes: [] }).code).toBe(
      "DT-02"
    );
    expect(dtCodeForRegisterRole({ side: "purchase", role: "grn", documentTypes: [] }).code).toBe(
      "DT-03"
    );
    expect(dtCodeForRegisterRole({ side: "purchase", role: "invoice", documentTypes: [] }).code).toBe(
      "DT-01"
    );
  });
});
