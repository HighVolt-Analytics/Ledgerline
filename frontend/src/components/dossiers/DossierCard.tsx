import { Link } from "react-router-dom";
import { AlertTriangle, ArrowRight, Ban } from "lucide-react";
import { DossierOutcomeBadge, DossierTypeBadge } from "@/components/dossiers/DossierOutcomeBadge";
import { DossierPipelinePhaseStrip } from "@/components/dossiers/DossierPipelinePhaseStrip";
import type { DossierSummary } from "@/lib/dossiers";
import {
  DOSSIER_PIPELINE_STAGES,
  dossierBlockerFromSummary,
  dossierOutcomeLabel,
  dossierStageLabel,
} from "@/lib/dossiers";
import { linkedDocumentCounts } from "@/lib/dossierLinkedDocuments";
import { money } from "@/lib/format";

function supportingDocLabel(present: number, required: number): string | null {
  if (required <= 0) return null;
  if (present >= required) return "Supporting document attached";
  return `Supporting docs ${present}/${required}`;
}

export function DossierCard({ dossier }: { dossier: DossierSummary }) {
  const blocker = dossierBlockerFromSummary(dossier);
  const bundle = linkedDocumentCounts(dossier.linkedDocuments);
  const stagesComplete = dossier.pipeline.filter(
    (step) => step.state === "pass" || step.state === "waived"
  ).length;
  const totalStages = DOSSIER_PIPELINE_STAGES.length;
  const progressPct = Math.round((stagesComplete / totalStages) * 100);
  const supportingLabel = supportingDocLabel(bundle.present, bundle.required);
  const showBlockedStatus = dossier.outcome === "blocked";

  return (
    <Link
      to={`/dossiers/${encodeURIComponent(dossier.id)}`}
      className="dossier-card group"
      data-testid={`card-dossier-${dossier.id}`}
    >
      <div className="dossier-card__upper">
        <div className="dossier-card__head">
          <div className="dossier-card__vendor">{dossier.vendor}</div>
          <DossierTypeBadge code={dossier.documentTypeCode} title={dossier.documentTypeTitle} />
        </div>

        <div className="dossier-card__meta tnum">
          {dossier.counterpartyLabel ?? "Counterparty"} · {dossier.id} · {dossier.invoiceRef}
        </div>

        <DossierPipelinePhaseStrip
          pipeline={dossier.pipeline}
          className="dossier-card__pipeline"
          variant="connected"
        />

        <div className="dossier-card__notice-slot">
          {blocker ? (
            <div className="dossier-card__notice">
              <div className="dossier-card__notice-title">
                <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden />
                <span>
                  {dossierStageLabel(blocker.stageId, dossier.routeTarget)} failed
                </span>
              </div>
              <p className="dossier-card__notice-detail">{blocker.reason}</p>
              {blocker.exceptionCode ? (
                <span className="dossier-card__exception-code tnum">[{blocker.exceptionCode}]</span>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <div className="dossier-card__footer">
        <div className="dossier-card__progress-block">
          <div className="dossier-card__progress-track" aria-hidden>
            <span
              className="dossier-card__progress-fill"
              style={{ width: `${progressPct}%` }}
            />
          </div>
          <p className="dossier-card__progress-label tnum">
            {stagesComplete} / {totalStages} stages completed
          </p>
        </div>

        <div className="dossier-card__metrics">
          <div className="dossier-card__metric">
            <span className="dossier-card__metric-label">Amount</span>
            <span className="dossier-card__metric-value tnum">
              {money(dossier.total, dossier.currency)}
            </span>
          </div>
          <div className="dossier-card__metric dossier-card__metric--status">
            <span className="dossier-card__metric-label">Status</span>
            <span className="dossier-card__metric-value dossier-card__status-value">
              {showBlockedStatus ? (
                <>
                  <Ban className="h-3.5 w-3.5 shrink-0 text-destructive" aria-hidden />
                  <span>{dossierOutcomeLabel(dossier.outcome)}</span>
                </>
              ) : (
                <DossierOutcomeBadge outcome={dossier.outcome} />
              )}
            </span>
          </div>
        </div>

        <div className="dossier-card__supporting-slot">
          {supportingLabel ? (
            <p className="dossier-card__supporting">{supportingLabel}</p>
          ) : null}
        </div>

        <div className="dossier-card__open">
          Open
          <ArrowRight className="h-3 w-3" />
        </div>
      </div>
    </Link>
  );
}
