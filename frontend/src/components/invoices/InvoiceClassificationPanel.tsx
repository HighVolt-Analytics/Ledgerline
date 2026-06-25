import type { InvoiceClassificationAudit } from "@/api/types";

type InvoiceClassificationPanelProps = {
  audit: InvoiceClassificationAudit | null;
  loading?: boolean;
};

function pct(value: number | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

const WEIGHT_RULE = 0.45;
const WEIGHT_FIELDS = 0.30;
const WEIGHT_PARSE = 0.15;
const WEIGHT_HEADING = 0.10;

function blendedConfidence(breakdown: NonNullable<InvoiceClassificationAudit["score_breakdown"]>): number {
  const rule = breakdown.rule_strength ?? 0;
  const fields = breakdown.field_completeness ?? 0;
  const parse = breakdown.parse_score ?? 0;
  const heading = breakdown.heading_alignment ?? 0;
  return (
    WEIGHT_RULE * rule +
    WEIGHT_FIELDS * fields +
    WEIGHT_PARSE * parse +
    WEIGHT_HEADING * heading
  );
}

function displayConfidence(audit: InvoiceClassificationAudit): string {
  const breakdown = audit.score_breakdown;
  if (breakdown?.confidence != null) {
    return pct(breakdown.confidence);
  }
  if (breakdown) {
    return pct(blendedConfidence(breakdown));
  }
  return pct(audit.document_type_confidence);
}

export function InvoiceClassificationPanel({ audit, loading }: InvoiceClassificationPanelProps) {
  if (loading) {
    return (
      <div className="rounded-md border border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
        Loading classification…
      </div>
    );
  }
  if (!audit?.document_type_code) {
    return null;
  }
  const conflicts =
    audit.signal_conflicts ?? audit.score_breakdown?.signal_conflicts ?? [];
  const breakdown = audit.score_breakdown;

  return (
    <div className="rounded-md border border-border bg-muted/20 px-3 py-2.5 text-xs space-y-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="font-medium text-foreground">Document type</span>
        <span className="text-foreground">
          {audit.document_type_code}
          {audit.document_type_title ? ` · ${audit.document_type_title}` : ""}
        </span>
        <span className="text-muted-foreground tnum">
          {displayConfidence(audit)} confidence
        </span>
        {audit.needs_review ? (
          <span className="text-amber-700 dark:text-amber-400">Needs review</span>
        ) : null}
      </div>
      {audit.reason ? <p className="text-muted-foreground">{audit.reason}</p> : null}
      {conflicts.length ? (
        <p className="text-amber-700 dark:text-amber-400">
          Signal conflicts: {conflicts.join("; ")}
        </p>
      ) : null}
      {breakdown ? (
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-muted-foreground sm:grid-cols-4">
          <div>
            <dt>Rule match</dt>
            <dd className="text-foreground tnum">{pct(breakdown.rule_strength)}</dd>
          </div>
          <div>
            <dt>Fields</dt>
            <dd className="text-foreground tnum">{pct(breakdown.field_completeness)}</dd>
          </div>
          <div>
            <dt>Parse</dt>
            <dd className="text-foreground tnum">{pct(breakdown.parse_score)}</dd>
          </div>
          <div>
            <dt>Heading</dt>
            <dd className="text-foreground tnum">{pct(breakdown.heading_alignment)}</dd>
          </div>
        </dl>
      ) : null}
    </div>
  );
}
