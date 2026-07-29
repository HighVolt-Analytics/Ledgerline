/** Dual Processing audit tabs — Understood (vision) vs Not understood (legacy OCR). */

export type PipelineActivePath = "understood" | "not_understood" | "unknown";

export const UNDERSTOOD_AUDIT_STAGES = new Set([
  "Received",
  "Duplicate",
  "Storage",
  "File validity",
  "Vision understand",
  "Vision header",
  "DT mapped",
  "Bundle",
  "Vault",
  "Parsed",
  "Validated",
  "Approved",
  "Mapped",
  "Match",
  "Journal",
  "Reconcile",
  "Posted",
]);

export const NOT_UNDERSTOOD_AUDIT_STAGES = new Set([
  "Received",
  "Duplicate",
  "Storage",
  "File validity",
  "Vision understand",
  "Image quality",
  "Layout readiness",
  "OCR",
  "OCR quality",
  "Classified",
  "Gate",
  "Parsed",
  "Validated",
  "Mapped",
  "Approved",
  "Posted",
]);

export function filterPipelineStepsForPath<T extends { stage: string }>(
  steps: T[],
  path: "understood" | "not_understood"
): T[] {
  const allowed = path === "understood" ? UNDERSTOOD_AUDIT_STAGES : NOT_UNDERSTOOD_AUDIT_STAGES;
  return steps.filter((step) => allowed.has(step.stage));
}

export function defaultAuditPathTab(
  activePath: PipelineActivePath | null | undefined
): "understood" | "not_understood" {
  if (activePath === "not_understood") return "not_understood";
  return "understood";
}
