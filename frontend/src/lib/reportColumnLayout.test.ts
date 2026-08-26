import { describe, expect, it } from "vitest";
import {
  applyColumnLayout,
  insertKeyInCatalogOrder,
  moveVisibleKey,
} from "@/lib/reportColumnLayout";

describe("applyColumnLayout", () => {
  const columns = ["Vendor", "Invoice no.", "Total", "Status"];
  const rows = [
    { cells: ["Acme", "INV-1", "10.00", "processed"] },
    { cells: ["Beta", "INV-2", "20.00", "processed"], emphasize: true },
  ];

  it("reorders and hides columns without changing row count", () => {
    const result = applyColumnLayout(columns, rows, ["Status", "Missing", "Invoice no."]);
    expect(result.columns).toEqual(["Status", "Invoice no."]);
    expect(result.rows).toHaveLength(2);
    expect(result.rows[0].cells).toEqual(["processed", "INV-1"]);
    expect(result.rows[1].emphasize).toBe(true);
  });

  it("falls back to all columns when no keys match", () => {
    const result = applyColumnLayout(columns, rows, ["Nope"]);
    expect(result.columns).toEqual(columns);
    expect(result.rows[0].cells).toEqual(rows[0].cells);
  });

  it("does not mutate the saved key list when dropping stale headers", () => {
    const saved = ["Status", "Removed Column", "Invoice no."];
    applyColumnLayout(columns, rows, saved);
    expect(saved).toEqual(["Status", "Removed Column", "Invoice no."]);
  });
});

describe("insertKeyInCatalogOrder", () => {
  it("reinserts a hidden column in catalog order", () => {
    expect(
      insertKeyInCatalogOrder(["Vendor", "Total"], "Invoice no.", [
        "Vendor",
        "Invoice no.",
        "Total",
      ])
    ).toEqual(["Vendor", "Invoice no.", "Total"]);
  });
});

describe("moveVisibleKey", () => {
  it("moves a column up and ignores out-of-range moves", () => {
    expect(moveVisibleKey(["A", "B", "C"], 2, -1)).toEqual(["A", "C", "B"]);
    expect(moveVisibleKey(["A", "B"], 0, -1)).toEqual(["A", "B"]);
  });
});
