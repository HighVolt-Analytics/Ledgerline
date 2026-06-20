import { Clock } from "lucide-react";
import { StatusPill } from "@/components/StatusPill";
import type { DossierSummary } from "@/lib/dossiers";
import { money } from "@/lib/format";
import { cn } from "@/lib/cn";

function confidenceFillClass(confidence: number): string {
  if (confidence >= 95) return "dossier-conf-fill--high";
  if (confidence >= 85) return "dossier-conf-fill--good";
  if (confidence >= 70) return "dossier-conf-fill--warn";
  return "dossier-conf-fill--bad";
}

export function DossierSummaryStrip({ dossier }: { dossier: DossierSummary }) {
  return (
    <div className="dossier-kpi-grid">
      <div className="dossier-kpi-card">
        <div className="dossier-kpi-label">Document total</div>
        <div className="dossier-kpi-value tnum">{money(dossier.total, dossier.currency)}</div>
        <div className="dossier-kpi-sub">
          Subtotal {money(dossier.subtotal, dossier.currency)} · Tax{" "}
          {money(dossier.tax, dossier.currency)}
        </div>
      </div>

      <div className="dossier-kpi-card">
        <div className="dossier-kpi-label">Classification</div>
        <div className="mt-1">
          <StatusPill className="border-border bg-muted/40 text-foreground">
            {dossier.classificationLabel}
          </StatusPill>
        </div>
        <div className="dossier-conf-row">
          <span className="dossier-conf-label">conf.</span>
          <div className="dossier-conf-track">
            <span
              className={cn("dossier-conf-fill", confidenceFillClass(dossier.classificationConfidence))}
              style={{ width: `${dossier.classificationConfidence}%` }}
            />
          </div>
          <span className="tnum text-xs text-muted-foreground">
            {dossier.classificationConfidence}%
          </span>
        </div>
      </div>

      <div className="dossier-kpi-card">
        <div className="dossier-kpi-label">Fraud risk</div>
        <div className="dossier-risk-row">
          <span className={cn("dossier-risk-dot", `dossier-risk-dot--${dossier.fraudRisk}`)} />
          {dossier.fraudRisk}
        </div>
        <div className="dossier-kpi-sub">
          {dossier.poReference ? `PO ${dossier.poReference}` : "Non-PO"}
        </div>
      </div>

      <div className="dossier-kpi-card">
        <div className="dossier-kpi-label">SLA</div>
        <div
          className={cn(
            "dossier-sla-row",
            dossier.slaBreached && "dossier-sla-row--breached"
          )}
        >
          <Clock className="h-3.5 w-3.5 shrink-0" />
          {dossier.slaLabel}
        </div>
        <div className="dossier-kpi-sub">Owner: {dossier.owner}</div>
      </div>
    </div>
  );
}

export function DossierOutcomeBanner({ message }: { message: string }) {
  if (!message) return null;
  return <div className="dossier-outcome-banner">{message}</div>;
}
