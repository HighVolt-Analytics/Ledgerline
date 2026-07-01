import type { DossierPipelineStep } from "@/lib/dossiers";
import { dossierPipelinePhases } from "@/lib/dossiers";
import type { CSSProperties } from "react";

const DOT = 10;

const PHASE_BG: Record<string, string> = {
  pass: "hsl(var(--chart-1))",
  fail: "hsl(var(--destructive))",
  waived: "hsl(43 74% 49%)",
  pending: "hsl(var(--muted-foreground) / 0.35)",
};

const stripStyle: CSSProperties = {
  display: "flex",
  alignItems: "flex-start",
  gap: 4,
  width: "100%",
};

const slotStyle: CSSProperties = {
  flex: "1 1 0%",
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  gap: 4,
  minWidth: 0,
};

function dotStyle(state: string): CSSProperties {
  return {
    display: "block",
    width: DOT,
    height: DOT,
    borderRadius: "50%",
    backgroundColor: PHASE_BG[state] ?? PHASE_BG.pending,
    flexShrink: 0,
  };
}

const labelStyle: CSSProperties = {
  fontSize: 9,
  fontWeight: 500,
  letterSpacing: "0.02em",
  color: "hsl(var(--muted-foreground))",
  textAlign: "center",
  lineHeight: 1.2,
  overflow: "hidden",
  textOverflow: "ellipsis",
  whiteSpace: "nowrap",
  width: "100%",
};

type Props = {
  pipeline: DossierPipelineStep[];
  className?: string;
  style?: CSSProperties;
};

/** Phase dots for list cards — full stage detail stays on dossier page. */
export function DossierPipelinePhaseStrip({ pipeline, className, style }: Props) {
  const phases = dossierPipelinePhases(pipeline);

  return (
    <div
      className={className}
      style={{ ...stripStyle, ...style }}
      role="img"
      aria-label="Pipeline phase summary"
    >
      {phases.map((phase) => (
        <span key={phase.phaseId} style={slotStyle} title={`${phase.label}: ${phase.state}`}>
          <span style={dotStyle(phase.state)} />
          <span style={labelStyle}>{phase.label}</span>
        </span>
      ))}
    </div>
  );
}
