import { Link } from "react-router-dom";
import { AlertTriangle, ArrowUpRight } from "lucide-react";
import { DossierOutcomeBadge, DossierTypeBadge } from "@/components/dossiers/DossierOutcomeBadge";
import { DossierPipelinePhaseStrip } from "@/components/dossiers/DossierPipelinePhaseStrip";
import type { DossierSummary } from "@/lib/dossiers";
import {
  dossierBlockerFromSummary,
  dossierStageLabel,
  pipelineProgressSummary,
} from "@/lib/dossiers";
import { linkedDocumentCounts } from "@/lib/dossierLinkedDocuments";
import { money } from "@/lib/format";

export function DossierCard({ dossier }: { dossier: DossierSummary }) {
  const blocker = dossierBlockerFromSummary(dossier);
  const progress = pipelineProgressSummary(dossier.pipeline, dossier.routeTarget);
  const bundle = linkedDocumentCounts(dossier.linkedDocuments);

  return (
    <Link
      to={`/dossiers/${encodeURIComponent(dossier.id)}`}
      className="dossier-card group"
      data-testid={`card-dossier-${dossier.id}`}
    >
      <div className="dossier-card__head">
        <div className="min-w-0">
          <div className="dossier-card__vendor">{dossier.vendor}</div>
          <div className="dossier-card__meta">
            {dossier.counterpartyLabel ?? "Counterparty"} · {dossier.id} · {dossier.invoiceRef}
          </div>
        </div>
        <DossierTypeBadge code={dossier.documentTypeCode} title={dossier.documentTypeTitle} />
      </div>

      <DossierPipelinePhaseStrip
        pipeline={dossier.pipeline}
        className="dossier-card__pipeline"
        showLegend
      />

      {blocker ? (
        <div className="dossier-card__blocker">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <div className="min-w-0">
            <div className="dossier-card__blocker-title">
              Failed at {dossierStageLabel(blocker.stageId, dossier.routeTarget)}
              {blocker.exceptionCode ? (
                <span className="dossier-pipeline-stage__code tnum ml-1.5">{blocker.exceptionCode}</span>
              ) : null}
            </div>
            <p className="dossier-card__blocker-detail">{blocker.reason}</p>
          </div>
        </div>
      ) : null}

      <div className="dossier-card__stats">
        <span className="dossier-card__stat--muted">{progress}</span>
      </div>

      <div className="dossier-card__foot">
        <div>
          <div className="dossier-card__amount tnum">{money(dossier.total, dossier.currency)}</div>
          <div className="dossier-card__bundle">
            Supporting docs {bundle.present}/{bundle.required}
          </div>
        </div>
        <div className="dossier-card__foot-right">
          <DossierOutcomeBadge outcome={dossier.outcome} />
          <span className="dossier-card__open">
            Open
            <ArrowUpRight className="h-3 w-3" />
          </span>
        </div>
      </div>
    </Link>
  );
}
