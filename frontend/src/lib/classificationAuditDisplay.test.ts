import { describe, expect, it } from "vitest";
import type { InvoiceClassificationAudit } from "@/api/types";
import {
  autoRouteThresholdSummary,
  classificationStatusMessage,
  formatClassificationConfidence,
  formatDtCodeWithName,
  requiresClassificationConfirm,
  reviewReasonLabel,
} from "@/lib/classificationAuditDisplay";

describe("formatDtCodeWithName", () => {
  const catalogue = [
    { code: "DT-11", title: "Purchase Invoice", shortTitle: "Invoice" },
  ] as never;

  it("shows code and catalogue title", () => {
    expect(formatDtCodeWithName(catalogue, "DT-11")).toBe("DT-11 · Purchase Invoice");
  });

  it("falls back to code when not in catalogue", () => {
    expect(formatDtCodeWithName(catalogue, "DT-99")).toBe("DT-99");
  });

  it("shows em dash for empty code", () => {
    expect(formatDtCodeWithName(catalogue, "")).toBe("—");
  });
});

describe("formatClassificationConfidence", () => {
  it("shows one decimal place without rounding up to the next whole percent", () => {
    expect(formatClassificationConfidence(0.846)).toBe("84.6%");
    expect(formatClassificationConfidence(0.849)).toBe("84.9%");
    expect(formatClassificationConfidence(0.95)).toBe("95.0%");
  });
});

describe("autoRouteThresholdSummary", () => {
  it("shows org and DT thresholds when they differ", () => {
    const audit: InvoiceClassificationAudit = {
      min_route_confidence: 0.85,
      org_auto_route_min_confidence: 0.85,
      dt_min_route_confidence: 0.65,
    };
    expect(autoRouteThresholdSummary(audit)).toBe(
      "Auto-route bar: 85.0% (org 85.0%, DT 65.0%)"
    );
  });
});

describe("classificationStatusMessage", () => {
  it("does not claim policy agreement when policy winner is absent", () => {
    const audit: InvoiceClassificationAudit = {
      compare_passed: true,
      policy_winner_dt: "",
    };
    expect(classificationStatusMessage(audit)).toBe(
      "Auto-classified — confidence met the routing threshold."
    );
  });

  it("mentions policy when a policy winner exists", () => {
    const audit: InvoiceClassificationAudit = {
      compare_passed: true,
      policy_winner_dt: "DT-03",
    };
    expect(classificationStatusMessage(audit)).toBe(
      "Auto-classified — LLM and policy agree."
    );
  });
});

describe("requiresClassificationConfirm", () => {
  it("requires confirm when awaiting classification", () => {
    expect(
      requiresClassificationConfirm({
        evaluation_status: "awaiting_classification",
        status: "exception",
        document_type_code: null,
      })
    ).toBe(true);
  });

  it("does not require confirm when document type is applied", () => {
    expect(
      requiresClassificationConfirm({
        evaluation_status: "auto_coded",
        status: "processed",
        document_type_code: "DT-06",
      })
    ).toBe(false);
  });

  it("does not require confirm for rescan queue", () => {
    expect(
      requiresClassificationConfirm({
        evaluation_status: "needs_rescan",
        status: "exception",
        document_type_code: null,
      })
    ).toBe(false);
  });
});

describe("reviewReasonLabel", () => {
  it("maps known review codes to readable labels", () => {
    expect(reviewReasonLabel("LLM_LOW_CONF")).toBe(
      "LLM confidence below auto-route threshold"
    );
    expect(reviewReasonLabel("CLASSIFIER_RULE_MISMATCH")).toBe(
      "Custom classifier rules do not match document text"
    );
  });
});
