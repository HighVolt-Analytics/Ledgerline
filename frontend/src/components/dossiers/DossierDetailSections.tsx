import { SectionBlock } from "@/components/SectionBlock";
import { DossierApprovalPanel } from "@/components/dossiers/DossierApprovalPanel";
import { DossierLinkedDocumentsPanel } from "@/components/dossiers/DossierLinkedDocumentsPanel";
import { DossierPipelineTimeline } from "@/components/dossiers/DossierPipelineTimeline";
import type { DossierSummary } from "@/lib/dossiers";

export { DossierPipelineTimeline };

export function DossierPipelinePanel({ pipeline }: { pipeline: DossierSummary["pipeline"] }) {
  return (
    <SectionBlock
      label="Processing pipeline"
      description="15 steps from upload to archive. Expand a step for validation checks and audit detail."
      className="dossier-detail-grid__main"
    >
      <DossierPipelineTimeline pipeline={pipeline} />
    </SectionBlock>
  );
}

export { DossierApprovalPanel, DossierLinkedDocumentsPanel };
