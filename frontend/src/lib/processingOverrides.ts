/** Per-invoice pipeline step skip catalog (mirrors backend). */

import type { ProcessingOverrides } from "@/api/types";

export type ProcessingOverrideStepId =
  | "image_quality"
  | "classification"
  | "field_confidence"
  | "vendor_drift"
  | "playbook"
  | "validation"
  | "mapping_review"
  | "vendor_registration"
  | "line_gl_mapping";

export type ProcessingOverrideStepDef = {
  id: ProcessingOverrideStepId;
  label: string;
  hint: string;
};

export const PROCESSING_OVERRIDE_STEPS: ProcessingOverrideStepDef[] = [
  {
    id: "image_quality",
    label: "Image quality gate",
    hint: "Skip low OCR text / sparse scan checks on reprocess.",
  },
  {
    id: "classification",
    label: "Classify + confidence gate",
    hint: "Use the document type already on this invoice; requires DT to be set.",
  },
  {
    id: "field_confidence",
    label: "Field confidence review",
    hint: "Continue when extracted fields are below confidence threshold.",
  },
  {
    id: "vendor_drift",
    label: "Vendor classification drift",
    hint: "Ignore vendor DT drift warnings on reprocess.",
  },
  {
    id: "playbook",
    label: "Playbook / supporting document gates",
    hint: "Skip playbook mandatory-field, PO/SO linkage, and missing supporting-document holds.",
  },
  {
    id: "validation",
    label: "Validation rules",
    hint: "Bypass configured VR checks on reprocess.",
  },
  {
    id: "mapping_review",
    label: "GL mapping review",
    hint: "Apply mapping without manual GL review.",
  },
  {
    id: "vendor_registration",
    label: "Vendor registration hold",
    hint: "Continue when the vendor is not yet in the vendor registry.",
  },
  {
    id: "line_gl_mapping",
    label: "Line GL mapping",
    hint: "Skip LLM sub-ledger assignment for line items.",
  },
];

export const SKIPPABLE_STEP_IDS = new Set(
  PROCESSING_OVERRIDE_STEPS.map((s) => s.id)
);

export function normaliseSkipSteps(
  raw: ProcessingOverrides | null | undefined
): ProcessingOverrideStepId[] {
  if (!raw?.skip_steps?.length) return [];
  return raw.skip_steps.filter((id) => SKIPPABLE_STEP_IDS.has(id));
}

export function skipStepsFromInvoice(
  overrides: ProcessingOverrides | null | undefined
): ProcessingOverrideStepId[] {
  return normaliseSkipSteps(overrides);
}

export function processingOverridesPayload(
  skipSteps: ProcessingOverrideStepId[]
): ProcessingOverrides | null {
  const cleaned = [...new Set(skipSteps.filter((id) => SKIPPABLE_STEP_IDS.has(id)))].sort();
  if (!cleaned.length) return null;
  return { skip_steps: cleaned };
}

export function isStepRunning(
  skipSteps: ProcessingOverrideStepId[],
  stepId: ProcessingOverrideStepId
): boolean {
  return !skipSteps.includes(stepId);
}

export function toggleStepRunning(
  skipSteps: ProcessingOverrideStepId[],
  stepId: ProcessingOverrideStepId,
  run: boolean
): ProcessingOverrideStepId[] {
  const set = new Set(skipSteps);
  if (run) set.delete(stepId);
  else set.add(stepId);
  return [...set].sort();
}

export function processingOverridesChanged(
  skipSteps: ProcessingOverrideStepId[],
  current: ProcessingOverrides | null | undefined
): boolean {
  const next = processingOverridesPayload(skipSteps);
  const prev = processingOverridesPayload(skipStepsFromInvoice(current));
  return JSON.stringify(next) !== JSON.stringify(prev);
}

export function processingOverridesPatchFromDraft(
  skipSteps: ProcessingOverrideStepId[],
  current: ProcessingOverrides | null | undefined
): ProcessingOverrides | null | undefined {
  if (!processingOverridesChanged(skipSteps, current)) return undefined;
  return processingOverridesPayload(skipSteps);
}
