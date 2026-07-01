import { describe, expect, it } from "vitest";
import {
  processingOverridesChanged,
  processingOverridesPayload,
  skipStepsFromInvoice,
  toggleStepRunning,
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
});
