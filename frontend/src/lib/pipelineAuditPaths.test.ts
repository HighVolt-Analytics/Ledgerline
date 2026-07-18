import { describe, expect, it } from "vitest";
import {
  defaultAuditPathTab,
  filterPipelineStepsForPath,
  NOT_UNDERSTOOD_AUDIT_STAGES,
  UNDERSTOOD_AUDIT_STAGES,
} from "@/lib/pipelineAuditPaths";

describe("pipelineAuditPaths", () => {
  it("filters understood stages only", () => {
    const steps = [
      { stage: "Storage" },
      { stage: "Vision header" },
      { stage: "OCR" },
      { stage: "Validated" },
      { stage: "Bundle" },
    ];
    const filtered = filterPipelineStepsForPath(steps, "understood");
    expect(filtered.map((s) => s.stage)).toEqual(["Storage", "Vision header", "Bundle"]);
    for (const stage of filtered.map((s) => s.stage)) {
      expect(UNDERSTOOD_AUDIT_STAGES.has(stage)).toBe(true);
    }
  });

  it("filters not-understood stages only", () => {
    const steps = [
      { stage: "Vision header" },
      { stage: "OCR" },
      { stage: "Validated" },
      { stage: "Bundle" },
    ];
    const filtered = filterPipelineStepsForPath(steps, "not_understood");
    expect(filtered.map((s) => s.stage)).toEqual(["OCR", "Validated"]);
    for (const stage of filtered.map((s) => s.stage)) {
      expect(NOT_UNDERSTOOD_AUDIT_STAGES.has(stage)).toBe(true);
    }
  });

  it("defaults tab from active_path", () => {
    expect(defaultAuditPathTab("understood")).toBe("understood");
    expect(defaultAuditPathTab("not_understood")).toBe("not_understood");
    expect(defaultAuditPathTab("unknown")).toBe("understood");
  });
});
