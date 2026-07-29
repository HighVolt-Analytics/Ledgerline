import { SectionBlock } from "@/components/SectionBlock";
import { DossierApprovalPanel } from "@/components/dossiers/DossierApprovalPanel";
import { DossierLinkedDocumentsPanel } from "@/components/dossiers/DossierLinkedDocumentsPanel";
import { DossierPipelineTimeline } from "@/components/dossiers/DossierPipelineTimeline";
import {
  isUnderstoodVaultOnlyPipeline,
  type DossierSummary,
} from "@/lib/dossiers";

export { DossierPipelineTimeline };

export function DossierPipelinePanel({
  pipeline,
  routeTarget,
  pipelinePath,
}: {
  pipeline: DossierSummary["pipeline"];
  routeTarget?: string | null;
  pipelinePath?: DossierSummary["pipelinePath"];
}) {
  const understood = pipelinePath === "understood";
  const vaultOnly = understood && isUnderstoodVaultOnlyPipeline(pipeline, pipelinePath);
  const stageCount = pipeline.length;
  return (
    <SectionBlock
      label="Processing pipeline"
      description={
        understood
          ? vaultOnly
            ? `${stageCount} stages on the understood path — capture through vault (posting not run).`
            : `${stageCount} stages on the understood path — vault, then validate → match → approve → map → journal → reconcile → post.`
          : "20 stages across 5 phases from upload to archive. Expand a stage for validation checks and audit detail."
      }
      className="dossier-detail-grid__main"
    >
      <DossierPipelineTimeline
        pipeline={pipeline}
        routeTarget={routeTarget}
        pipelinePath={pipelinePath}
      />
    </SectionBlock>
  );
}

export { DossierApprovalPanel, DossierLinkedDocumentsPanel };
