import type { DossierPipelineStep, DossierPipelinePhaseId } from "@/lib/dossiers";
import { dossierPipelinePhases, dossierStageStateLabel } from "@/lib/dossiers";
import type { DossierPhaseDocumentBinding } from "@/lib/dossierPhaseDocuments";
import { cn } from "@/lib/cn";

type Props = {
  pipeline: DossierPipelineStep[];
  className?: string;
  showLegend?: boolean;
  variant?: "default" | "connected";
  activePhaseId?: DossierPipelinePhaseId | null;
  phaseBindings?: DossierPhaseDocumentBinding[];
  onPhaseSelect?: (phaseId: DossierPipelinePhaseId) => void;
};

function lineTone(state: ReturnType<typeof dossierPipelinePhases>[number]["state"]): string {
  if (state === "pass") return "dossier-card-pipeline__line--pass";
  if (state === "waived") return "dossier-card-pipeline__line--waived";
  if (state === "fail") return "dossier-card-pipeline__line--fail";
  return "dossier-card-pipeline__line--pending";
}

/** Phase dots for list cards — full stage detail stays on dossier page. */
export function DossierPipelinePhaseStrip({
  pipeline,
  className,
  showLegend = false,
  variant = "default",
  activePhaseId = null,
  phaseBindings,
  onPhaseSelect,
}: Props) {
  const phases = dossierPipelinePhases(pipeline);
  const interactive = Boolean(onPhaseSelect);

  if (variant === "connected") {
    return (
      <div className={cn("dossier-card-pipeline", className)}>
        <div
          className="dossier-card-pipeline__track"
          role={interactive ? "tablist" : "img"}
          aria-label="Pipeline phase summary"
        >
          {phases.map((phase, index) => {
            const binding = phaseBindings?.find((row) => row.phaseId === phase.phaseId);
            const title = binding
              ? `${phase.label}: ${binding.headline} — ${binding.detail}`
              : `${phase.label}: ${dossierStageStateLabel(phase.state)}`;
            const SegmentTag = interactive ? "button" : "div";
            return (
              <div key={phase.phaseId} className="dossier-card-pipeline__segment">
                {index > 0 ? (
                  <span
                    className={cn(
                      "dossier-card-pipeline__line",
                      lineTone(phases[index - 1]!.state)
                    )}
                    aria-hidden
                  />
                ) : null}
                <SegmentTag
                  type={interactive ? "button" : undefined}
                  role={interactive ? "tab" : undefined}
                  aria-selected={interactive ? activePhaseId === phase.phaseId : undefined}
                  className={cn(
                    "dossier-card-pipeline__dot-btn",
                    interactive && "dossier-card-pipeline__dot-btn--interactive",
                    activePhaseId === phase.phaseId && "dossier-card-pipeline__dot-btn--active"
                  )}
                  title={title}
                  onClick={
                    interactive
                      ? (event) => {
                          event.preventDefault();
                          event.stopPropagation();
                          onPhaseSelect?.(phase.phaseId);
                        }
                      : undefined
                  }
                >
                  <span
                    className={cn(
                      "dossier-card-pipeline__dot",
                      `dossier-card-pipeline__dot--${phase.state}`
                    )}
                  />
                </SegmentTag>
              </div>
            );
          })}
        </div>
        <div className="dossier-card-pipeline__labels" aria-hidden>
          {phases.map((phase) => (
            <span key={phase.phaseId} className="dossier-card-pipeline__label">
              {phase.label}
            </span>
          ))}
        </div>
      </div>
    );
  }

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
