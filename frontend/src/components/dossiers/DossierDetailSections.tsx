import { SectionBlock } from "@/components/SectionBlock";
import { DossierApprovalPanel } from "@/components/dossiers/DossierApprovalPanel";
import { DossierLinkedDocumentsPanel } from "@/components/dossiers/DossierLinkedDocumentsPanel";
import { DossierPipelineTimeline } from "@/components/dossiers/DossierPipelineTimeline";
import type { DossierSummary } from "@/lib/dossiers";

export { DossierPipelineTimeline };

export function DossierPipelinePanel({ pipeline }: { pipeline: DossierSummary["pipeline"] }) {
  return (
    <SectionBlock
      label="Full pipeline"
      description="15 stages in Ledgerline order — duplicate file hash immediately after ingest, then parse through archive. Expand any stage for audit-level checks."
      className="dossier-detail-grid__main"
    >
      <DossierPipelineTimeline pipeline={pipeline} />
    </SectionBlock>
  );
}

export { DossierApprovalPanel, DossierLinkedDocumentsPanel };
