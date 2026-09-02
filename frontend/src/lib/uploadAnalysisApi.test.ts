import { describe, expect, it } from "vitest";
import { mapMatrixAnalysisToDataset, uploadAnalysisQueryParams } from "@/lib/uploadAnalysisApi";
import type { UploadAnalysisScope } from "@/lib/uploadAnalysisScope";

describe("uploadAnalysisQueryParams", () => {
  const baseScope: UploadAnalysisScope = {
    channel: "email",
    view: "summary",
    documentAreas: ["purchase"],
    approvalFilter: ["review"],
    searchQuery: "acme",
  };

  it("maps upload section filters to matrix analysis params", () => {
    expect(uploadAnalysisQueryParams(baseScope)).toEqual({
      capture_source: "email",
      route_target: "Purchase Management",
      q: "acme",
      approval_board_column: "review",
    });
  });

  it("omits channel filter for all documents", () => {
    expect(
      uploadAnalysisQueryParams({
        ...baseScope,
        channel: "all",
        documentAreas: [],
        approvalFilter: [],
        searchQuery: "",
      })
    ).toEqual({});
  });
});

describe("mapMatrixAnalysisToDataset", () => {
  it("maps API payload into overlay dataset with per-currency totals", () => {
    const scope: UploadAnalysisScope = {
      channel: "upload",
      view: "summary",
      documentAreas: ["team"],
      approvalFilter: [],
      searchQuery: "",
    };
    const dataset = mapMatrixAnalysisToDataset(scope, {
      approval_board: [
        {
          key: "review",
          column: "To Review",
          items: 3,
          value_by_currency: { AUD: 1200, USD: 450 },
          avg_wait_days: 1.2,
          flagged: 1,
        },
      ],
      processing_funnel: [
        { stage: "Received", count: 5, delta: null, pct: 100 },
        { stage: "Posted", count: 2, delta: -3, pct: 40 },
      ],
      exception_mix: [
        {
          type: "Anomaly Detected",
          items: 1,
          at_risk_by_currency: { AUD: 500, INR: 9800 },
          severity: "Medium",
        },
      ],
      summary: {
        document_count: 5,
        flagged: 1,
        duplicates: 0,
        awaiting: 0,
        paid_this_month: 0,
        truncated: false,
        analyzed_count: 5,
      },
    });

    expect(dataset.scopeLabel).toContain("Upload");
    expect(dataset.approvalBoard).toHaveLength(4);
    expect(dataset.approvalBoard[0]?.valueByCurrency).toEqual({ AUD: 1200, USD: 450 });
    expect(dataset.exceptionMix[0]?.atRiskByCurrency).toEqual({ AUD: 500, INR: 9800 });
    expect(dataset.processingFunnel).toHaveLength(2);
    expect(dataset.summary.documentCount).toBe(5);
  });
});
