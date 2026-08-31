import { describe, expect, it } from "vitest";
import {
  EMPTY_UPLOAD_APPROVAL_COUNTS,
  EMPTY_UPLOAD_APPROVAL_FILTER,
  approvalBoardCountsEqual,
  parseUploadApprovalFilter,
  parseUploadDocumentArea,
  parseUploadDocumentAreas,
  routeTargetsForDocumentAreas,
  serializeUploadDocumentAreas,
  toggleUploadApprovalFilter,
  toggleUploadDocumentArea,
  selectUploadDocumentArea,
} from "@/lib/uploadApprovalFilter";

describe("parseUploadApprovalFilter", () => {
  it("returns the same empty array instance for All", () => {
    expect(parseUploadApprovalFilter(null)).toBe(EMPTY_UPLOAD_APPROVAL_FILTER);
    expect(parseUploadApprovalFilter("")).toBe(EMPTY_UPLOAD_APPROVAL_FILTER);
    expect(parseUploadApprovalFilter("all")).toBe(EMPTY_UPLOAD_APPROVAL_FILTER);
    expect(parseUploadApprovalFilter("nope")).toBe(EMPTY_UPLOAD_APPROVAL_FILTER);
    expect(parseUploadApprovalFilter(null)).toBe(parseUploadApprovalFilter("all"));
  });

  it("parses selected columns in catalog order", () => {
    expect(parseUploadApprovalFilter("rejected,review")).toEqual(["review", "rejected"]);
  });
});

describe("toggleUploadApprovalFilter", () => {
  it("returns the shared empty filter when selecting All", () => {
    expect(toggleUploadApprovalFilter(["review"], "all")).toBe(EMPTY_UPLOAD_APPROVAL_FILTER);
  });
});

describe("approvalBoardCountsEqual", () => {
  it("treats identical counts as equal without requiring the same object", () => {
    expect(
      approvalBoardCountsEqual(EMPTY_UPLOAD_APPROVAL_COUNTS, {
        all: 0,
        review: 0,
        processing: 0,
        approved: 0,
        rejected: 0,
      })
    ).toBe(true);
    expect(
      approvalBoardCountsEqual(EMPTY_UPLOAD_APPROVAL_COUNTS, {
        ...EMPTY_UPLOAD_APPROVAL_COUNTS,
        review: 1,
        all: 1,
      })
    ).toBe(false);
  });
});

describe("upload document area filters", () => {
  it("parses a single area and comma-separated areas", () => {
    expect(parseUploadDocumentAreas("purchase")).toEqual(["purchase"]);
    expect(parseUploadDocumentAreas("expenses,purchase")).toEqual(["expenses", "purchase"]);
    expect(parseUploadDocumentAreas("sales, team, unknown")).toEqual(["team", "sales"]);
  });

  it("selects one area at a time and clears back to Summary", () => {
    expect(selectUploadDocumentArea([], "team")).toEqual(["team"]);
    expect(selectUploadDocumentArea(["team"], "expenses")).toEqual(["expenses"]);
    expect(selectUploadDocumentArea(["team"], "team")).toEqual([]);
  });

  it("serializes empty as no URL param and maps areas to route targets", () => {
    expect(serializeUploadDocumentAreas([])).toBeNull();
    expect(serializeUploadDocumentAreas(["expenses", "purchase"])).toBe("expenses,purchase");
    expect(routeTargetsForDocumentAreas(["expenses", "purchase"])).toBe(
      "Expenses Management,Purchase Management"
    );
    expect(routeTargetsForDocumentAreas([])).toBeUndefined();
  });

  it("falls back to a single operations view token", () => {
    expect(parseUploadDocumentAreas(null, "purchases")).toEqual(["purchase"]);
    expect(parseUploadDocumentArea(null, "purchases")).toBe("purchase");
  });
});
