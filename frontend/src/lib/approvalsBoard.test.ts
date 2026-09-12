import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import {
  canShowApproveOnBoard,
  canShowConfirmOnBoard,
  canShowRejectOnApprovedBoard,
  canShowReprocessOnBoard,
  columnForInvoice,
  filterApprovedBoardRows,
  isPostedApprovedRow,
  isPreClassificationReview,
  isSystemFiledVaultTerminal,
  mergeBoardRowWithLocal,
  needsReviewQueueCount,
  reviewQueueCount,
  shouldClearProcessingId,
  systemFiledDocumentTypeOptions,
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

  it("puts vision_vaulted in Approved and vision_header_review by DT", () => {
    expect(
      columnForInvoice(inv(1, "exception", { evaluation_status: "vision_vaulted" }))
    ).toBe("approved");
    expect(
      columnForInvoice(inv(2, "exception", { evaluation_status: "vision_header_review" }))
    ).toBe("pending");
    expect(
      columnForInvoice(
        inv(4, "exception", {
          evaluation_status: "vision_header_review",
          document_type_code: "DT-07",
        })
      )
    ).toBe("awaiting");
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

  it("hides confirm on Review and Rejected, shows on Processing only", () => {
    const reviewInv = inv(1, "exception", {
      evaluation_status: "awaiting_classification",
    });
    const procInv = inv(2, "exception", {
      evaluation_status: "needs_review",
      document_type_code: "DT-03",
    });
    const rejectedInv = inv(3, "rejected");
    expect(canShowConfirmOnBoard(reviewInv, "pending")).toBe(false);
    expect(canShowConfirmOnBoard(procInv, "awaiting")).toBe(true);
    expect(canShowApproveOnBoard(procInv, "awaiting")).toBe(false);
    expect(canShowConfirmOnBoard(rejectedInv, "rejected")).toBe(false);
  });

  it("shows confirm for vision_header_review in Processing, not for vault-terminal", () => {
    const headerReview = inv(10, "exception", {
      evaluation_status: "vision_header_review",
      document_type_code: "DT-07",
    });
    const vaulted = inv(11, "exception", { evaluation_status: "vision_vaulted" });
    expect(canShowConfirmOnBoard(headerReview, "awaiting")).toBe(true);
    expect(canShowApproveOnBoard(headerReview, "awaiting")).toBe(false);
    expect(canShowConfirmOnBoard(headerReview, "pending")).toBe(false);
    expect(canShowConfirmOnBoard(vaulted, "awaiting")).toBe(false);
    expect(canShowConfirmOnBoard(vaulted, "approved")).toBe(false);
  });

  it("shows Approve only when the document is waiting on policy approval", () => {
    const held = inv(12, "exception", {
      evaluation_status: "pending_approval",
      document_type_code: "DT-05",
    });
    expect(canShowConfirmOnBoard(held, "awaiting")).toBe(true);
    expect(canShowApproveOnBoard(held, "awaiting")).toBe(true);
    expect(canShowApproveOnBoard(held, "pending")).toBe(false);
  });

  it("shows Approve on Review for without-document claims", () => {
    const withoutDoc = inv(13, "exception", {
      evaluation_status: "needs_review",
      document_type_code: "DT-05",
      has_stored_file: false,
      extracted_fields: { without_document: "true", manual_entry: "true" },
    });
    expect(canShowApproveOnBoard(withoutDoc, "pending")).toBe(true);
    expect(canShowApproveOnBoard(withoutDoc, "awaiting")).toBe(false);
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

describe("system-filed Approved filters", () => {
  it("isSystemFiledVaultTerminal is vision_vaulted only", () => {
    expect(
      isSystemFiledVaultTerminal(inv(1, "exception", { evaluation_status: "vision_vaulted" }))
    ).toBe(true);
    expect(isPostedApprovedRow(inv(2, "processed"))).toBe(true);
    expect(
      isSystemFiledVaultTerminal(inv(3, "processed", { evaluation_status: "auto_coded" }))
    ).toBe(false);
  });

  it("filterApprovedBoardRows splits Posted vs System filed", () => {
    const posted = inv(1, "processed");
    const filed = inv(2, "exception", {
      evaluation_status: "vision_vaulted",
      document_type_code: "DT-11",
    });
    const other = inv(3, "exception", { evaluation_status: "vision_vaulted", document_heading: "AWB" });
    const rows = [posted, filed, other];
    expect(filterApprovedBoardRows(rows, "posted").map((r) => r.id)).toEqual([1]);
    expect(filterApprovedBoardRows(rows, "system_filed").map((r) => r.id)).toEqual([2, 3]);
    expect(filterApprovedBoardRows(rows, "all").map((r) => r.id)).toEqual([1, 2, 3]);
  });

  it("DT filter matches system-filed rows by code or heading", () => {
    const filedDt = inv(2, "exception", {
      evaluation_status: "vision_vaulted",
      document_type_code: "DT-11",
    });
    const filedHeading = inv(3, "exception", {
      evaluation_status: "vision_vaulted",
      document_heading: "AIR WAYBILL",
    });
    const posted = inv(1, "processed", { document_type_code: "DT-11" });
    const rows = [posted, filedDt, filedHeading];
    expect(systemFiledDocumentTypeOptions(rows)).toEqual(["AIR WAYBILL", "DT-11"]);
    expect(
      filterApprovedBoardRows(rows, "system_filed", "DT-11").map((r) => r.id)
    ).toEqual([2]);
    expect(
      filterApprovedBoardRows(rows, "system_filed", "AIR WAYBILL").map((r) => r.id)
    ).toEqual([3]);
  });
});
