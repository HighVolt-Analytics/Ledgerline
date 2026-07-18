import { SectionBlock } from "@/components/SectionBlock";
import { DossierApprovalPanel } from "@/components/dossiers/DossierApprovalPanel";
import { DossierLinkedDocumentsPanel } from "@/components/dossiers/DossierLinkedDocumentsPanel";
import { DossierPipelineTimeline } from "@/components/dossiers/DossierPipelineTimeline";
import type { DossierSummary } from "@/lib/dossiers";

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
  const stageCount = pipeline.length;
  return (
    <SectionBlock
      label="Processing pipeline"
      description={
        understood
          ? `${stageCount} stages on the understood path — receive, duplicate check, vision header, soft bundle, and vault.`
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
