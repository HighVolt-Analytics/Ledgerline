import { describe, expect, it } from "vitest";

import type { ChartOfAccountRow } from "@/api/types";
import {
  filterCoaAccountsForPostingRole,
  resolveCoaAccountName,
} from "@/lib/coaAccountOptions";
import {
  defaultPostToLedger,
  suggestedLedgerForPlaybookProfile,
} from "@/lib/documentTypeGlDefaults";
import { hasValidPostTo, postToConfigWarnings } from "@/lib/documentTypePostToValidation";
import { emptyDocumentTypePostTo } from "@/lib/v5DocumentTypes";

const accounts: ChartOfAccountRow[] = [
  { code: "5100", name: "Raw Materials", type: "Expense" },
  { code: "6100", name: "Operating Expenses", type: "Expense" },
];

const salesCoa: ChartOfAccountRow[] = [
  { code: "1", name: "sales", type: "Revenue" },
  { code: "1", name: "sales", type: "Asset" },
  { code: "1200", name: "Accounts Receivable", type: "Asset" },
  { code: "2200", name: "GST Collected", type: "Liability" },
];

describe("documentTypeGlDefaults", () => {
  it("suggests finance-aligned ledger names", () => {
    expect(suggestedLedgerForPlaybookProfile("po_goods")).toBe("Raw Materials");
    expect(defaultPostToLedger("po_goods", accounts)).toBe("Raw Materials");
  });

  it("picks sole revenue account when suggested name is missing", () => {
    const sparseCoa = [{ code: "1", name: "sales", type: "Revenue" as const }];
    expect(defaultPostToLedger("ar_goods", sparseCoa)).toBe("sales");
    expect(defaultPostToLedger("", sparseCoa, "Sales Management")).toBe("sales");
  });
});

describe("coaAccountOptions", () => {
  it("resolves account names against tenant COA", () => {
    expect(resolveCoaAccountName("operating expenses", accounts)).toBe("Operating Expenses");
  });

  it("filters sales main ledger to revenue accounts", () => {
    const revenueOnly = filterCoaAccountsForPostingRole(salesCoa, "revenue");
    expect(revenueOnly.map((row) => row.name)).toEqual(["sales"]);
  });

  it("excludes mis-typed sales asset from receivable role", () => {
    const misTyped = [
      { code: "1", name: "sales", type: "Asset" as const },
      { code: "1200", name: "Accounts Receivable", type: "Asset" as const },
    ];
    const receivableOnly = filterCoaAccountsForPostingRole(misTyped, "receivable");
    expect(receivableOnly.map((row) => row.name)).toEqual(["Accounts Receivable"]);
  });

  it("filters tax collected to output-tax liabilities", () => {
    const taxOnly = filterCoaAccountsForPostingRole(salesCoa, "tax_collected");
    expect(taxOnly.map((row) => row.name)).toEqual(["GST Collected"]);
  });
});

describe("documentTypePostToValidation", () => {
  it("requires Post to for transactional types", () => {
    const docType = {
      posting: "Yes",
      postTo: { ...emptyDocumentTypePostTo(), ledger: "Operating Expenses" },
    };
    expect(hasValidPostTo(docType, accounts)).toBe(true);
    expect(
      hasValidPostTo({ posting: "Yes", postTo: emptyDocumentTypePostTo() }, accounts)
    ).toBe(false);
    expect(postToConfigWarnings({ ...docType, code: "DT-1" } as never, accounts)).toHaveLength(0);
    expect(
      postToConfigWarnings(
        {
          posting: "Yes",
          postTo: emptyDocumentTypePostTo(),
          code: "DT-1",
        } as never,
        accounts
      ).some((row) => row.id === "post-to-required")
    ).toBe(true);
  });

  it("warns when sub-ledger is not in catalog for ledger with sub-ledgers", () => {
    const coaWithSubs: ChartOfAccountRow[] = [
      {
        code: "6110",
        name: "Cloud Hosting Expense",
        type: "Expense",
        subLedgers: [{ code: "01", name: "AWS Production" }],
      },
    ];
    const warnings = postToConfigWarnings(
      {
        posting: "Yes",
        postTo: {
          ...emptyDocumentTypePostTo(),
          ledger: "Cloud Hosting Expense",
          subLedger: "Legacy Free Text",
        },
        code: "DT-1",
      } as never,
      coaWithSubs
    );
    expect(warnings.some((row) => row.id === "post-to-sub-ledger-not-in-coa")).toBe(true);
  });
});
