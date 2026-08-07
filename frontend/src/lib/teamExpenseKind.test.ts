import { describe, expect, it } from "vitest";

import {
  inferTeamExpenseKindFromLabels,
  reconcileTeamExpenseKindForDocumentType,
} from "./teamExpenseKind";

describe("teamExpenseKind reconcile", () => {
  it("infers claim and advance from titles", () => {
    expect(inferTeamExpenseKindFromLabels("Employee expense claim")).toBe("expense_claim");
    expect(inferTeamExpenseKindFromLabels("Employee advance request")).toBe(
      "advance_requisition"
    );
  });

  it("lets clear titles win over swapped pins", () => {
    expect(
      reconcileTeamExpenseKindForDocumentType({
        title: "Employee expense claim",
        configured: "advance_requisition",
      })
    ).toBe("expense_claim");
    expect(
      reconcileTeamExpenseKindForDocumentType({
        title: "Employee advance request",
        configured: "expense_claim",
      })
    ).toBe("advance_requisition");
  });
});
