import { describe, expect, it } from "vitest";
import {
  EMPTY_UPLOAD_APPROVAL_COUNTS,
  EMPTY_UPLOAD_APPROVAL_FILTER,
  approvalBoardCountsEqual,
  parseUploadApprovalFilter,
  toggleUploadApprovalFilter,
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
