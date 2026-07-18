import type { InvoiceClassificationAudit } from "@/api/types";
import { documentTypeLabelForCode } from "@/lib/documentTypeResolve";
import type { DocumentTypeDefinition } from "@/lib/v5DocumentTypes";

/** One decimal place — avoids rounding 84.6% up to 85%. */
export function formatClassificationConfidence(value: number | undefined | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

/** DT code with catalogue title, e.g. "DT-11 · Purchase Invoice". */
export function formatDtCodeWithName(
  documentTypes: DocumentTypeDefinition[],
  code: string | null | undefined
): string {
  const token = (code ?? "").trim();
  if (!token) return "—";
  const name = documentTypeLabelForCode(documentTypes, token);
  if (!name || name.toUpperCase() === token.toUpperCase()) return token;
  return `${token} · ${name}`;
}

const REVIEW_REASON_LABELS: Record<string, string> = {
  LLM_LOW_CONF: "LLM confidence below auto-route threshold",
  CLASSIFIER_RULE_MISMATCH: "Custom classifier rules do not match document text",
  DT_NOT_IN_CATALOGUE: "Suggested type is not in your Rule Book",
  DT_DISABLED: "Suggested document type is disabled",
  LLM_INVALID: "Classification model returned no usable result",
  OCR_SPARSE: "OCR text is too sparse",
  IMAGE_QUALITY_LOW: "Scan or image quality is too poor",
  DT_MISMATCH: "LLM and policy classifiers disagree",
  POLICY_LOW_CONF: "Policy classifier confidence is too low",
  PERSPECTIVE_AMBIGUOUS: "Could not determine purchase vs sales perspective",
  EXTRACTION_GAP: "Required fields missing for suggested document type",
  NEVER_AUTO_POLICY: "Document type is configured to always require review",
  PROVIDER_UNAVAILABLE: "Document AI provider unavailable",
  VENDOR_CLASSIFICATION_DRIFT: "Vendor classification differs from recent history",
  FIELD_CONFIDENCE_LOW: "Extracted field confidence is too low",
  citation_failed: "Citation grounding failed for one or more fields",
};

export function reviewReasonLabel(code: string): string {
  const token = code.trim();
  return REVIEW_REASON_LABELS[token] ?? token.replaceAll("_", " ").toLowerCase();
}

export function classificationReviewReasons(audit: InvoiceClassificationAudit): string[] {
  const raw = audit.review_reasons;
  if (Array.isArray(raw) && raw.length) return raw.map(String);
  if (audit.needs_review) return ["NEEDS_REVIEW"];
  return [];
}

export function autoRouteThresholdSummary(audit: InvoiceClassificationAudit): string | null {
  const effective = audit.min_route_confidence;
  if (effective == null || Number.isNaN(effective)) return null;

  const org =
    audit.org_auto_route_min_confidence ?? audit.auto_route_min_confidence ?? null;
  const dt = audit.dt_min_route_confidence ?? null;

  const effectiveLabel = formatClassificationConfidence(effective);
  if (org != null && dt != null && Math.abs(org - dt) > 0.0001) {
    return `Auto-route bar: ${effectiveLabel} (org ${formatClassificationConfidence(org)}, DT ${formatClassificationConfidence(dt)})`;
  }
  if (org != null) {
    return `Auto-route bar: ${effectiveLabel} (org-wide ${formatClassificationConfidence(org)})`;
  }
  return `Auto-route bar: ${effectiveLabel}`;
}

export function classificationStatusMessage(audit: InvoiceClassificationAudit): string | null {
  if (classificationReviewReasons(audit).length) return null;
  if (!audit.compare_passed) return null;

  const policyDt = (audit.policy_winner_dt ?? "").trim();
  if (policyDt) {
    return "Auto-classified — LLM and policy agree.";
  }
  return "Auto-classified — confidence met the routing threshold.";
}

export function requiresClassificationConfirm(
  inv:
    | {
        evaluation_status?: string | null;
        status?: string | null;
        document_type_code?: string | null;
      }
    | null
    | undefined
): boolean {
  if (!inv) return false;
  if (
    inv.evaluation_status === "awaiting_classification" ||
    inv.evaluation_status === "vision_header_review"
  ) {
    return true;
  }
  if (inv.evaluation_status === "vision_vaulted") return false;
  if (inv.evaluation_status === "needs_rescan") return false;

  const storedDt = (inv.document_type_code ?? "").trim();
  if (!storedDt && inv.status === "exception") return true;
  return false;
}
