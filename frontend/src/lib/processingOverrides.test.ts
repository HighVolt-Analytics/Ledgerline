import { describe, expect, it } from "vitest";
import {
  processingOverridesChanged,
  processingOverridesPayload,
  skipStepIdForAuditStage,
  skipStepsFromInvoice,
  toggleStepRunning,
  UNMATCHED_OVERRIDE_STEP_IDS,
} from "@/lib/processingOverrides";

describe("processingOverrides", () => {
  it("round-trips skip steps through payload", () => {
    const skipSteps = toggleStepRunning([], "validation", false);
    expect(skipSteps).toEqual(["validation"]);
    expect(processingOverridesPayload(skipSteps)).toEqual({
      skip_steps: ["validation"],
    });
  });

  it("reads skip steps from invoice overrides", () => {
    expect(
      skipStepsFromInvoice({ skip_steps: ["playbook", "bogus", "validation"] })
    ).toEqual(["playbook", "validation"]);
  });

  it("detects when overrides changed", () => {
    expect(
      processingOverridesChanged(["validation"], { skip_steps: ["playbook"] })
    ).toBe(true);
    expect(
      processingOverridesChanged(["validation"], { skip_steps: ["validation"] })
    ).toBe(false);
  });

  it("maps audit stages to skip step ids", () => {
    expect(skipStepIdForAuditStage("OCR quality")).toBe("image_quality");
    expect(skipStepIdForAuditStage("Validated")).toBe("validation");
    expect(skipStepIdForAuditStage("Received")).toBeNull();
  });

  it("lists override ids with no timeline stage", () => {
    expect(UNMATCHED_OVERRIDE_STEP_IDS).toEqual([
      "field_confidence",
      "vendor_drift",
      "vendor_registration",
      "line_gl_mapping",
    ]);
  });
});
