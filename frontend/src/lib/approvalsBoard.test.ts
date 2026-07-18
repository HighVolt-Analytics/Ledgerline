import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import {
  canShowApproveOnBoard,
  canShowRejectOnApprovedBoard,
  canShowReprocessOnBoard,
  columnForInvoice,
  isPreClassificationReview,
  mergeBoardRowWithLocal,
  needsReviewQueueCount,
  reviewQueueCount,
  shouldClearProcessingId,
} from "@/lib/approvalsBoard";

function inv(
  id: number,
  status: string,
  extra: Partial<Invoice> = {}
): Invoice {
  return {
    id,
    status,
    created_at: "2026-01-01T00:00:00Z",
    currency: "AUD",
    ...extra,
  } as Invoice;
}

describe("columnForInvoice", () => {
  it("places pre-classification exceptions in Review", () => {
    expect(
      columnForInvoice(
        inv(1, "exception", { evaluation_status: "awaiting_classification" })
      )
    ).toBe("pending");
    expect(
      columnForInvoice(inv(2, "exception", { evaluation_status: "needs_rescan" }))
    ).toBe("pending");
    expect(columnForInvoice(inv(3, "exception"))).toBe("pending");
  });

  it("places post-classification exceptions in Processing", () => {
    for (const evaluation_status of ["needs_review", "awaiting_po", "pending_vendor"] as const) {
      expect(
        columnForInvoice(
          inv(1, "exception", {
            evaluation_status,
            document_type_code: "DT-03",
          })
        )
      ).toBe("awaiting");
    }
  });

  it("places pipeline statuses in Processing", () => {
    for (const status of [
      "pending",
      "parsing",
      "validating",
      "mapping",
      "journaling",
      "reconciling",
    ]) {
      expect(columnForInvoice(inv(1, status, { document_type_code: "DT-03" }))).toBe(
        "awaiting"
      );
    }
  });

  it("places processed invoices in Approved", () => {
    expect(
      columnForInvoice(
        inv(1, "processed", {
          evaluation_status: "auto_coded",
          document_type_code: "DT-03",
        })
      )
    ).toBe("approved");
  });

  it("places rejected invoices in Rejected", () => {
    expect(columnForInvoice(inv(1, "rejected"))).toBe("rejected");
    expect(columnForInvoice(inv(1, "duplicate_skipped"))).toBe("rejected");
  });

  it("prefers processingIds over stale exception status", () => {
    expect(
      columnForInvoice(inv(1, "exception"), undefined, new Set([1]))
    ).toBe("awaiting");
  });

  it("prefers pinnedRejectedIds over processed status", () => {
    expect(columnForInvoice(inv(1, "processed"), new Set([1]))).toBe("rejected");
  });

  it("uses approval_board_column from API when present", () => {
    expect(
      columnForInvoice(
        inv(1, "exception", {
          evaluation_status: "awaiting_classification",
          approval_board_column: "processing",
        })
      )
    ).toBe("awaiting");
  });

  it("puts vision_vaulted in Approved and vision_header_review in To review", () => {
    expect(
      columnForInvoice(inv(1, "exception", { evaluation_status: "vision_vaulted" }))
    ).toBe("approved");
    expect(
      columnForInvoice(inv(2, "exception", { evaluation_status: "vision_header_review" }))
    ).toBe("pending");
    expect(
      columnForInvoice(
        inv(3, "exception", {
          evaluation_status: "awaiting_classification",
          extracted_fields: { vision_bundle_kind: "soft", vision_bundle_key: "INV-1" },
        })
      )
    ).toBe("approved");
  });
});

describe("isPreClassificationReview and approve visibility", () => {
  it("flags Review column items", () => {
    expect(
      isPreClassificationReview(
        inv(1, "exception", { evaluation_status: "awaiting_classification" })
      )
    ).toBe(true);
    expect(
      isPreClassificationReview(
        inv(2, "exception", {
          evaluation_status: "needs_review",
          document_type_code: "DT-03",
        })
      )
    ).toBe(false);
  });

  it("hides approve on Review and Rejected, shows on Processing only", () => {
    const reviewInv = inv(1, "exception", {
      evaluation_status: "awaiting_classification",
    });
    const procInv = inv(2, "exception", {
      evaluation_status: "needs_review",
      document_type_code: "DT-03",
    });
    const rejectedInv = inv(3, "rejected");
    expect(canShowApproveOnBoard(reviewInv, "pending")).toBe(false);
    expect(canShowApproveOnBoard(procInv, "awaiting")).toBe(true);
    expect(canShowApproveOnBoard(rejectedInv, "rejected")).toBe(false);
  });

  it("shows reprocess only for rejected status with stored file on Rejected column", () => {
    const rejectedInv = inv(3, "rejected", {
      has_stored_file: true,
      raw_file_path: "azureblob://invoices/test.pdf",
    });
    const rejectedNoFile = inv(4, "rejected");
    const duplicateInv = inv(5, "duplicate_skipped");
    const processedInv = inv(6, "processed");
    expect(canShowReprocessOnBoard(rejectedInv, "rejected")).toBe(true);
    expect(canShowReprocessOnBoard(rejectedNoFile, "rejected")).toBe(false);
    expect(canShowReprocessOnBoard(duplicateInv, "rejected")).toBe(false);
    expect(canShowReprocessOnBoard(processedInv, "approved")).toBe(false);
    expect(canShowReprocessOnBoard(rejectedInv, "awaiting")).toBe(false);
  });

  it("shows Reject on Approved for processed and vision-vaulted exception docs", () => {
    expect(canShowRejectOnApprovedBoard(inv(1, "processed"))).toBe(true);
    expect(
      canShowRejectOnApprovedBoard(
        inv(2, "exception", { evaluation_status: "vision_vaulted" })
      )
    ).toBe(true);
    expect(
      canShowRejectOnApprovedBoard(
        inv(3, "exception", { evaluation_status: "needs_review", document_type_code: "DT-01" })
      )
    ).toBe(false);
  });
});

describe("reviewQueueCount", () => {
  it("counts only Review column items", () => {
    const rows = [
      inv(1, "exception", { evaluation_status: "awaiting_classification" }),
      inv(2, "exception", {
        evaluation_status: "needs_review",
        document_type_code: "DT-03",
      }),
      inv(3, "parsing"),
    ];
    expect(reviewQueueCount(rows)).toBe(1);
  });

  it("needsReviewQueueCount excludes pending_approval", () => {
    const rows = [
      inv(1, "exception", { evaluation_status: "needs_review", document_type_code: "DT-03" }),
      inv(2, "exception", { evaluation_status: "pending_approval", document_type_code: "DT-26" }),
    ];
    expect(needsReviewQueueCount(rows)).toBe(1);
  });
});

describe("shouldClearProcessingId", () => {
  it("keeps tracking while pipeline is active", () => {
    expect(shouldClearProcessingId("parsing", false)).toBe(false);
    expect(shouldClearProcessingId("pending", false)).toBe(false);
  });

  it("does not clear on exception until pipeline was observed", () => {
    expect(shouldClearProcessingId("exception", false)).toBe(false);
    expect(shouldClearProcessingId("exception", true)).toBe(true);
  });

  it("clears on processed or rejected", () => {
    expect(shouldClearProcessingId("processed", false)).toBe(true);
    expect(shouldClearProcessingId("rejected", false)).toBe(true);
  });
});

describe("mergeBoardRowWithLocal", () => {
  it("prefers settled server row over stale optimistic pending", () => {
    const local = inv(7, "pending");
    const remote = inv(7, "exception", {
      vendor: "Acme Pty Ltd",
      total: "1200",
      document_type_code: "DT-03",
    });
    expect(mergeBoardRowWithLocal(remote, local, new Set([7]))).toEqual(remote);
  });

  it("uses server status when not optimistically processing", () => {
    const local = inv(7, "rejected");
    const remote = inv(7, "processed");
    expect(mergeBoardRowWithLocal(remote, local, new Set())).toEqual(remote);
  });

  it("accepts remote pipeline status once backend catches up", () => {
    const local = inv(7, "pending");
    const remote = inv(7, "parsing");
    expect(mergeBoardRowWithLocal(remote, local, new Set([7]))).toEqual(remote);
  });

  it("accepts remote processed row after upload pipeline completes", () => {
    const local = inv(7, "pending");
    const remote = inv(7, "processed", {
      vendor: "Vendor Co",
      total: "500",
      document_type_code: "DT-01",
    });
    expect(mergeBoardRowWithLocal(remote, local, new Set([7]))).toEqual(remote);
  });
});
