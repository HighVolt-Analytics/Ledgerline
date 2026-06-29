import type { DossierPipelineStep } from "@/lib/dossiers";
import { DOSSIER_PIPELINE_STAGES } from "@/lib/dossiers";
import type { CSSProperties } from "react";

const DOT_SIZE = 6;

const PIPELINE_BG: Record<DossierPipelineStep["state"], string> = {
  pass: "hsl(var(--chart-1))",
  fail: "hsl(var(--destructive))",
  waived: "hsl(43 74% 49%)",
  pending: "hsl(var(--muted-foreground) / 0.35)",
};

const STRIP_STYLE: CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 2,
  width: "100%",
  minHeight: DOT_SIZE,
};

const SLOT_STYLE: CSSProperties = {
  flex: "1 1 0%",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  minWidth: 0,
};

function dotStyle(state: DossierPipelineStep["state"]): CSSProperties {
  return {
    display: "block",
    width: DOT_SIZE,
    height: DOT_SIZE,
    borderRadius: "50%",
    backgroundColor: PIPELINE_BG[state],
    flexShrink: 0,
  };
}

type DossierPipelineDotsProps = {
  pipeline: DossierPipelineStep[];
  className?: string;
  style?: CSSProperties;
};

/** One dot per pipeline stage (full detail on dossier page). */
export function DossierPipelineDots({ pipeline, className, style }: DossierPipelineDotsProps) {
  const byStage = new Map(pipeline.map((step) => [step.stageId, step.state]));

  return (
    <div
      className={className}
      style={{ ...STRIP_STYLE, ...style }}
      role="img"
      aria-label="Pipeline stage status"
    >
      {DOSSIER_PIPELINE_STAGES.map((stage) => {
        const state = byStage.get(stage.id) ?? "pending";
        return (
          <span key={stage.id} style={SLOT_STYLE} title={`${stage.label}: ${state}`}>
            <span style={dotStyle(state)} />
          </span>
        );
      })}
    </div>
  );
}
