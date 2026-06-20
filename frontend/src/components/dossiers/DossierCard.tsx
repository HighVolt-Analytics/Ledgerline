import { Link } from "react-router-dom";
import { AlertTriangle, ArrowUpRight } from "lucide-react";
import { DossierOutcomeBadge, DossierTypeBadge } from "@/components/dossiers/DossierOutcomeBadge";
import { DossierPipelinePhaseStrip } from "@/components/dossiers/DossierPipelinePhaseStrip";
import type { DossierSummary } from "@/lib/dossiers";
import {
  dossierPipelineCounts,
  dossierStageLabel,
  firstPipelineFailure,
} from "@/lib/dossiers";
import { linkedDocumentCounts } from "@/lib/dossierLinkedDocuments";

import { money } from "@/lib/format";

export function DossierCard({ dossier }: { dossier: DossierSummary }) {
  const { pass, fail, waived } = dossierPipelineCounts(dossier.pipeline);
  const firstFail = firstPipelineFailure(dossier.pipeline);
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
            {dossier.id} · {dossier.invoiceRef}
          </div>
        </div>
        <DossierTypeBadge code={dossier.documentTypeCode} title={dossier.documentTypeTitle} />
      </div>

      <DossierPipelinePhaseStrip
        pipeline={dossier.pipeline}
        className="dossier-card__pipeline"
      />

      {firstFail ? (
        <div className="dossier-card__blocker">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            Blocked at {dossierStageLabel(firstFail.stageId)}
            {firstFail.exceptionCode ? ` · ${firstFail.exceptionCode}` : ""}
          </span>
        </div>
      ) : null}

      <div className="dossier-card__stats">
        <span className="dossier-card__stat--pass">{pass} pass</span>
        {fail > 0 ? <span className="dossier-card__stat--fail">{fail} fail</span> : null}
        {waived > 0 ? <span className="dossier-card__stat--waived">{waived} waived</span> : null}
      </div>

      <div className="dossier-card__foot">
        <div>
          <div className="dossier-card__amount tnum">{money(dossier.total, dossier.currency)}</div>
          <div className="dossier-card__bundle">
            Bundle {bundle.present}/{bundle.required} linked
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
