import type { DossierPipelineStep } from "@/lib/dossiers";
import { dossierPipelinePhases, dossierStageStateLabel } from "@/lib/dossiers";
import { cn } from "@/lib/cn";

type Props = {
  pipeline: DossierPipelineStep[];
  className?: string;
  showLegend?: boolean;
};

/** Phase dots for list cards — full stage detail stays on dossier page. */
export function DossierPipelinePhaseStrip({ pipeline, className, showLegend = false }: Props) {
  const phases = dossierPipelinePhases(pipeline);

  return (
    <div className={cn("dossier-pipeline-phase-strip-wrap", className)}>
      <div className="dossier-pipeline-strip" role="img" aria-label="Pipeline phase summary">
        {phases.map((phase) => (
          <span
            key={phase.phaseId}
            className="dossier-pipeline-slot"
            title={`${phase.label}: ${dossierStageStateLabel(phase.state)}`}
          >
            <span className={cn("dossier-pipeline-dot", `dossier-pipeline-dot--${phase.state}`)} />
            <span className="dossier-pipeline-slot__label">{phase.label}</span>
          </span>
        ))}
      </div>
      {showLegend ? (
        <div className="dossier-pipeline-legend" aria-hidden>
          <span className="dossier-pipeline-legend__item">
            <span className="dossier-pipeline-dot dossier-pipeline-dot--pass" />
            Complete
          </span>
          <span className="dossier-pipeline-legend__item">
            <span className="dossier-pipeline-dot dossier-pipeline-dot--fail" />
            Failed
          </span>
          <span className="dossier-pipeline-legend__item">
            <span className="dossier-pipeline-dot dossier-pipeline-dot--pending" />
            Waiting
          </span>
          <span className="dossier-pipeline-legend__item">
            <span className="dossier-pipeline-dot dossier-pipeline-dot--waived" />
            Skipped
          </span>
        </div>
      ) : null}
    </div>
  );
}
