import { describe, expect, it } from "vitest";
import type { Invoice } from "@/api/types";
import {
  canShowApproveOnBoard,
  columnForInvoice,
  isPreClassificationReview,
  mergeBoardRowWithLocal,
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
      expect(columnForInvoice(inv(1, status, { document_type_code: "DT-03" })).toBe(
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

  it("hides approve on Review, shows on Processing", () => {
    const reviewInv = inv(1, "exception", {
      evaluation_status: "awaiting_classification",
    });
    const procInv = inv(2, "exception", {
      evaluation_status: "needs_review",
      document_type_code: "DT-03",
    });
    expect(canShowApproveOnBoard(reviewInv, "pending")).toBe(false);
    expect(canShowApproveOnBoard(procInv, "awaiting")).toBe(true);
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
  it("keeps optimistic pending while approve is in flight", () => {
    const local = inv(7, "pending");
    const remote = inv(7, "exception");
    expect(mergeBoardRowWithLocal(remote, local, new Set([7]))).toEqual(local);
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
});
