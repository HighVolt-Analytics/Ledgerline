import { describe, expect, it } from "vitest";
import type { ReportCatalogItem } from "@/api/types";
import {
  favouriteItems,
  filterCatalogItems,
  groupCatalogByCategory,
} from "@/lib/reportCatalog";

const ITEMS: ReportCatalogItem[] = [
  {
    id: "invoice-register",
    name: "Invoice Register",
    description: "The source of truth for payables as of the period end. Vendor Spend, AP Aging and Payment Schedule read from here. Custom range still filters by invoice date.",
    category: "transactions",
    supports_compare: false,
  },
  {
    id: "cash-forecast",
    name: "Cash Forecast",
    description: "AP amounts due by date. Employee reimbursements are not included yet.",
    category: "transactions",
    supports_compare: false,
  },
  {
    id: "aged-payables",
    name: "Aged Payables",
    description: "Outstanding vendor balances bucketed by due date.",
    category: "payables_receivables",
    supports_compare: false,
  },
  {
    id: "control-centre",
    name: "Control Centre",
    description: "Prioritized exception queue.",
    category: "exceptions_controls",
    supports_compare: false,
  },
];

describe("filterCatalogItems", () => {
  it("filters by search across name, description, and id", () => {
    expect(filterCatalogItems(ITEMS, "cash", "all").map((item) => item.id)).toEqual([
      "cash-forecast",
    ]);
    expect(filterCatalogItems(ITEMS, "vendor", "all").map((item) => item.id)).toEqual([
      "invoice-register",
      "aged-payables",
    ]);
    expect(
      filterCatalogItems(ITEMS, "invoice-register", "all").map((item) => item.id)
    ).toEqual(["invoice-register"]);
  });

  it("filters by category tab", () => {
    expect(
      filterCatalogItems(ITEMS, "", "payables_receivables").map((item) => item.id)
    ).toEqual(["aged-payables"]);
    expect(
      filterCatalogItems(ITEMS, "cash", "transactions").map((item) => item.id)
    ).toEqual(["cash-forecast"]);
    expect(filterCatalogItems(ITEMS, "cash", "payables_receivables")).toEqual([]);
  });
});

describe("groupCatalogByCategory", () => {
  it("keeps category order and drops empty groups", () => {
    const groups = groupCatalogByCategory(ITEMS);
    expect(groups.map((group) => group.category)).toEqual([
      "payables_receivables",
      "transactions",
      "exceptions_controls",
    ]);
    expect(groups[1].items).toHaveLength(2);
  });
});

describe("favouriteItems", () => {
  it("returns starred reports in catalog order", () => {
    expect(
      favouriteItems(ITEMS, ["aged-payables", "invoice-register"]).map((item) => item.id)
    ).toEqual(["invoice-register", "aged-payables"]);
  });
});
